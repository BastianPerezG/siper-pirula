from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.contrib import messages
from core.models import Negocio
from inventario.models import Producto, Categoria
from pedidos.models import Pedido, PedidoItem, Cliente
from pedidos.emails import enviar_correo_pedido_creado
from pedidos.validators import validar_rut
from django.contrib.auth.models import User  # para crear el usuario
from pedidos.forms import RegistroClienteForm
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from .forms import CheckoutForm
from ventas.models import Venta
# Solo si vas a usar el SDK oficial:
try:
    from transbank.webpay.webpay_plus.transaction import Transaction
    from transbank.common.options import WebpayOptions
    from transbank.common.integration_type import IntegrationType
except ImportError:
    Transaction = None  # para que el proyecto no reviente si aún no instalas el SDK



CART_SESSION_KEY = "carrito"



def get_webpay_transaction():
    options = WebpayOptions(
        commerce_code=settings.TRANSBANK_COMMERCE_CODE,
        api_key=settings.TRANSBANK_API_KEY,
        integration_type=settings.TRANSBANK_ENVIRONMENT,
    )
    return Transaction(options)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def get_negocio_actual():
    # Para este proyecto asumimos una sola botillería
    return Negocio.objects.first()


def _get_cart(request):
    return request.session.get(CART_SESSION_KEY, {})


def _save_cart(request, cart):
    request.session[CART_SESSION_KEY] = cart
    request.session.modified = True


def _build_cart_items(request, negocio):
    """
    Convierte la sesión 'cart' en una lista uniforme de items.
    """
    cart = _get_cart(request)
    items = []
    total = 0

    for pid_str, cant in cart.items():
        try:
            producto = Producto.objects.get(
                pk=int(pid_str),
                negocio=negocio,
                activo=True,
            )
        except Producto.DoesNotExist:
            continue

        cant = int(cant)
        subtotal = producto.precio * cant

        items.append(
            {
                "producto": producto,
                "cantidad": cant,
                "subtotal": subtotal,
            }
        )

        total += subtotal

    return items, total

def limpiar_carrito_en_session(request):
    """
    Elimina el carrito de la sesión.
    """
    if CART_SESSION_KEY in request.session:
        del request.session[CART_SESSION_KEY]
        request.session.modified = True


# ------------------------------------------------------------------
# Vistas públicas
# ------------------------------------------------------------------

def tienda_home(request):
    """
    Portada de la tienda:
    muestra tarjetas grandes por categoría.
    Usa la Categoria del inventario.
    """
    negocio = get_negocio_actual()

    categorias = Categoria.objects.filter(
        negocio=negocio
    ).order_by("nombre")

    # Para cada categoría buscamos una imagen representativa:
    categorias_data = []
    for cat in categorias:
        producto_con_imagen = (
            Producto.objects
            .filter(
                negocio=negocio,
                categoria=cat,
                activo=True,
                imagen__isnull=False,
            )
            .first()
        )
        categorias_data.append(
            {
                "categoria": cat,
                "imagen": producto_con_imagen.imagen if producto_con_imagen else None,
            }
        )

    context = {
        "categorias_data": categorias_data,
    }
    return render(request, "tienda/home.html", context)



def categoria_detalle(request, categoria_id):
    """
    Listado de productos filtrado por categoría,
    accesible desde las tarjetas del home.
    """
    negocio = get_negocio_actual()

    categoria = get_object_or_404(
        Categoria,
        pk=categoria_id,
        negocio=negocio,
    )

    productos = Producto.objects.filter(
        negocio=negocio,
        categoria=categoria,
        activo=True,
    ).order_by("nombre")  # puedes cambiar a "precio" si quieres

    context = {
        "categoria": categoria,
        "productos": productos,
    }
    return render(request, "tienda/producto_lista.html", context)


@require_POST
def carrito_agregar(request, producto_id):
    negocio = get_negocio_actual()

    producto = get_object_or_404(
        Producto,
        pk=producto_id,
        negocio=negocio,
        activo=True,
    )

    # Validación real de stock
    if producto.stock_actual <= 0:
        messages.error(request, "Este producto no tiene stock disponible.")
        if producto.categoria and producto.categoria.slug:
            return redirect(f"{reverse('tienda:productos')}?categoria={producto.categoria.slug}")
        return redirect("tienda:productos")


    cart = _get_cart(request)
    pid = str(producto.id)
    cantidad_actual = int(cart.get(pid, 0))

    if cantidad_actual + 1 > producto.stock_actual:
        messages.error(request, "No hay más stock disponible para este producto.")
        return redirect("tienda:carrito_ver")

    cart[pid] = cantidad_actual + 1
    _save_cart(request, cart)

    messages.success(request, f"{producto.nombre} agregado al carrito.")

    return redirect("tienda:carrito_ver")


def carrito_eliminar(request, producto_id):
    cart = _get_cart(request)
    pid = str(producto_id)

    if pid in cart:
        del cart[pid]
        _save_cart(request, cart)

    return redirect("tienda:carrito_ver")


def carrito_actualizar(request):
    if request.method != "POST":
        return redirect("tienda:carrito_ver")

    negocio = get_negocio_actual()
    nuevo_cart = {}

    for key, value in request.POST.items():
        if not key.startswith("cant_"):
            continue

        pid = key.replace("cant_", "").strip()

        try:
            cantidad = int(value)
        except (ValueError, TypeError):
            continue

        if cantidad <= 0:
            continue

        # Validar producto y stock real
        try:
            producto = Producto.objects.get(
                pk=int(pid),
                negocio=negocio,
                activo=True
            )
        except Producto.DoesNotExist:
            continue

        if cantidad > producto.stock_actual:
            cantidad = producto.stock_actual

        nuevo_cart[pid] = cantidad

    _save_cart(request, nuevo_cart)

    if "go_checkout" in request.POST:
        return redirect("tienda:checkout")

    return redirect("tienda:carrito_ver")



def carrito_ver(request):
    negocio = get_negocio_actual()
    items, total = _build_cart_items(request, negocio)

    return render(
        request,
        "tienda/carrito.html",
        {"items": items, "total": total},
    )


# ------------------------------------------------------------------
# Checkout
# ------------------------------------------------------------------


def checkout_view(request):
    negocio = get_negocio_actual()

    # Ítems del carrito desde la sesión
    items, total = _build_cart_items(request, negocio)

    if not items:
        messages.warning(request, "Tu carrito está vacío.")
        return redirect("tienda:productos")

    if request.method == "POST":
        form = CheckoutForm(request.POST)

        if form.is_valid():
            datos = form.cleaned_data
            forma_pago = datos["forma_pago"]  # AHORA desde cleaned_data

            rut = datos.get("rut")
            cliente = None

            # Si viene RUT, lo usamos para buscar/crear cliente
            if rut:
                cliente, _ = Cliente.objects.get_or_create(
                    negocio=negocio,
                    rut=rut,
                    defaults={
                        "nombre": datos["nombre"],
                        "correo": datos["correo"],
                        "telefono": datos.get("telefono", ""),
                        "activo": True,
                    },
                )

            # Crear Pedido
            pedido = Pedido.objects.create(
                negocio=negocio,
                cliente=cliente,
                nombre=datos["nombre"],
                correo=datos["correo"],              # <- corregido
                telefono=datos.get("telefono", ""),  # <- corregido
                total_monto=total,
                forma_pago=forma_pago,
                estado=Pedido.EST_RECIBIDO,
            )

            # Crear ítems de pedido
            for item in items:
                PedidoItem.objects.create(
                    pedido=pedido,
                    producto=item["producto"],
                    cantidad=item["cantidad"],
                    precio=item["producto"].precio,
                )

            # Reservar stock
            pedido.crear_reservas_inventario()

            # Flujo según forma de pago
            if forma_pago == "RETIRO":
                pedido.marcar_pendiente_retiro()
                enviar_correo_pedido_creado(pedido)
                limpiar_carrito_en_session(request)

                messages.success(
                    request,
                    f"Tu pedido {pedido.codigo} fue creado correctamente. "
                    "Pagarás al retirar en la botillería.",
                )
                return redirect("tienda:checkout_exito", pedido_id=pedido.id)

            elif forma_pago == "WEBPAY":
                try:
                    url_pago, token = iniciar_pago_webpay(pedido, request)
                except Exception:
                    messages.error(
                        request,
                        "Ocurrió un problema al iniciar el pago con Webpay. "
                        "Intenta nuevamente o elige pagar al retirar."
                    )
                    return redirect("tienda:carrito_ver")

                pedido.webpay_token = token
                pedido.webpay_status = "iniciado"
                pedido.save(update_fields=["webpay_token", "webpay_status"])

                limpiar_carrito_en_session(request)
                return redirect(f"{url_pago}?token_ws={token}")

            else:
                messages.error(request, "Forma de pago no válida.")
                return redirect("tienda:carrito_ver")

        # Si el form NO es válido, caes aquí: solo volvemos a mostrar la página
        # con errores. No redirijas.
    else:
        # GET: prellenar con datos del usuario autenticado
        initial = {}
        if request.user.is_authenticated:
            initial["nombre"] = (
                request.user.get_full_name() or request.user.username
            )
            initial["correo"] = request.user.email

        form = CheckoutForm(initial=initial)

    context = {
        "negocio": negocio,
        "items": items,
        "total": total,
        "form": form,
    }
    return render(request, "tienda/checkout.html", context)


def checkout_exito_view(request, pedido_id):
    negocio = get_negocio_actual()
    pedido = get_object_or_404(
        Pedido,
        pk=pedido_id,
        negocio=negocio,
    )

    return render(
        request,
        "tienda/checkout_exito.html",
        {"pedido": pedido},
    )


# ------------------------------------------------------------------
# Autenticación de clientes
# ------------------------------------------------------------------

def registro_cliente_view(request):
    negocio = get_negocio_actual()

    if request.method == "POST":
        form = RegistroClienteForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            password = form.cleaned_data["password1"]

            # Crear usuario Django
            user = User.objects.create_user(
                username=username,
                email=form.cleaned_data.get("correo"),
                password=password,
            )

            # Crear cliente asociado
            cliente = form.save(commit=False)
            cliente.negocio = negocio
            cliente.user = user
            cliente.save()

            # Loguear inmediatamente
            login(request, user)
            messages.success(request, "Cuenta creada y sesión iniciada correctamente.")
            return redirect("tienda:home")
    else:
        form = RegistroClienteForm()

    return render(request, "tienda/registro.html", {"form": form})


def login_cliente_view(request):
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, "Sesión iniciada correctamente.")

            next_url = request.GET.get("next") or "tienda:home"
            return redirect(next_url)
    else:
        form = AuthenticationForm(request)

    return render(request, "tienda/login.html", {"form": form})


def logout_cliente_view(request):
    logout(request)
    messages.info(request, "Has cerrado sesión.")
    return redirect("tienda:home")


def productos_list_view(request):
    negocio = get_negocio_actual()

    categorias = Categoria.objects.filter(
        negocio=negocio,
        activa=True,
    ).order_by("orden", "nombre")

    categoria_slug = request.GET.get("categoria", "").strip()
    q = request.GET.get("q", "").strip()

    productos_qs = Producto.objects.filter(
        negocio=negocio,
        activo=True,
    ).select_related("categoria").order_by("nombre")

    categoria_activa = None
    if categoria_slug:
        categoria_activa = get_object_or_404(
            Categoria,
            slug=categoria_slug,
            negocio=negocio,
            activa=True,
        )
        productos_qs = productos_qs.filter(categoria=categoria_activa)

    if q:
        productos_qs = productos_qs.filter(nombre__icontains=q)

    paginator = Paginator(productos_qs, 24)  # 24 productos por página
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "categorias": categorias,
        "categoria_activa": categoria_activa,
        "categoria": categoria_activa,   # alias para el template
        "q": q,
        "page_obj": page_obj,
        "productos": page_obj,           # el template iterará sobre 'productos'
    }
    return render(request, "tienda/producto_lista.html", context)

def producto_detalle(request, producto_id):
    negocio = get_negocio_actual()

    producto = get_object_or_404(
        Producto,
        pk=producto_id,
        negocio=negocio,
        activo=True,
    )

    cart = _get_cart(request)
    cantidad_en_carrito = int(cart.get(str(producto.id), 0))

    context = {
        "producto": producto,
        "cantidad_en_carrito": cantidad_en_carrito,
    }
    return render(request, "tienda/producto_detalle.html", context)


def sugerencias_productos(request):
    negocio = get_negocio_actual()
    q = request.GET.get("q", "").strip()

    resultados = []
    if len(q) >= 2:
        productos = Producto.objects.filter(
            negocio=negocio,
            activo=True,
            nombre__icontains=q
        ).only("id", "nombre")[:10]

        resultados = [
            {"id": p.id, "nombre": p.nombre}
            for p in productos
        ]

    return JsonResponse(resultados, safe=False)



def iniciar_pago_webpay(pedido, request):
    """
    Crea la transacción Webpay Plus y devuelve (url, token).
    Lanza ValueError si el SDK no está instalado.
    """

    if Transaction is None:
        raise ValueError(
            "El SDK de Transbank no está instalado. "
            "Ejecuta: pip install transbank-sdk"
        )

    commerce_code = getattr(settings, "WEBPAY_COMMERCE_CODE", "597055555532")
    api_key = getattr(
        settings,
        "WEBPAY_API_KEY",
        "579B532A7440BB0C9079DED94D31EA1615BACEB56610332264630D42D0A36B1C",
    )
    options = WebpayOptions(
        commerce_code=commerce_code,
        api_key=api_key,
        integration_type=IntegrationType.TEST,  # integración (sandbox)
    )

    tx = Transaction(options)

    # buy_order debe ser único; usamos el código del pedido
    buy_order = pedido.codigo
    session_id = request.session.session_key or request.session.cycle_key()
    return_url = request.build_absolute_uri(reverse("tienda:webpay_retorno"))

    resp = tx.create(
        buy_order=buy_order,
        session_id=session_id,
        amount=float(pedido.total),
        return_url=return_url,
    )

    token = resp["token"]
    url = resp["url"]
    return url, token


def webpay_retorno_view(request):
    token = request.POST.get("token_ws") or request.GET.get("token_ws")
    if not token:
        messages.error(request, "Transacción inválida (falta token).")
        return redirect("tienda:home")

    tx = get_webpay_transaction()
    response = tx.commit(token)

    # Puedes imprimir en consola para ver la estructura del response
    # print(response)

    buy_order = response.get("buy_order")
    status = response.get("status")
    amount = response.get("amount")

    pedido = get_object_or_404(Pedido, codigo=buy_order)

    if status == "AUTHORIZED":
        # marcar pedido como pagado
        pedido.estado = Pedido.EST_PAGADO
        pedido.save()

        # generar venta desde pedido (sin tocar stock extra)
        venta = pedido.generar_venta(medio_pago=Venta.MED_TARJETA)

        # limpiar carrito y sesión
        request.session.pop("ultimo_pedido_id", None)
        limpiar_carrito_en_session(request)

        # mostrar página de éxito de pago
        return render(request, "tienda/webpay_exito.html", {
            "pedido": pedido,
            "venta": venta,
            "response": response,
        })
    else:
        # fallo / rechazo / abortada
        # aquí tú decides: ¿cancelar pedido y liberar stock?
        pedido.liberar_reservas_inventario()
        pedido.estado = Pedido.EST_CANCELADO
        pedido.save()

        return render(request, "tienda/webpay_error.html", {
            "pedido": pedido,
            "response": response,
        })


@csrf_exempt
def webpay_retorno_view(request):
    token = request.GET.get("token_ws") or request.POST.get("token_ws")
    if not token:
        messages.error(request, "No se recibió el token de Webpay.")
        return redirect("tienda:productos")

    if Transaction is None:
        messages.error(request, "El SDK de Transbank no está instalado.")
        return redirect("tienda:productos")

    # Buscar el pedido asociado a ese token
    try:
        pedido = Pedido.objects.get(webpay_token=token)
    except Pedido.DoesNotExist:
        messages.error(request, "No se encontró el pedido asociado al pago.")
        return redirect("tienda:productos")

    commerce_code = getattr(settings, "WEBPAY_COMMERCE_CODE", "597055555532")
    api_key = getattr(
        settings,
        "WEBPAY_API_KEY",
        "579B532A7440BB0C9079DED94D31EA1615BACEB56610332264630D42D0A36B1C",
    )
    options = WebpayOptions(
        commerce_code=commerce_code,
        api_key=api_key,
        integration_type=IntegrationType.TEST,
    )
    tx = Transaction(options)

    resp = tx.commit(token)
    status = resp.get("status")

    if status == "AUTHORIZED":
        pedido.marcar_pagado_descontar_stock()
        pedido.webpay_status = "pagado"
        pedido.save(update_fields=["webpay_status"])

        messages.success(
            request, f"Pago del pedido {pedido.codigo} autorizado correctamente."
        )
        return redirect("tienda:checkout_exito", pedido_id=pedido.id)
    else:
        pedido.webpay_status = status or "rechazado"
        pedido.marcar_cancelado_revertir_reserva()
        pedido.save(update_fields=["webpay_status"])

        messages.error(request, "El pago fue rechazado o anulado.")
        return redirect("tienda:productos")
