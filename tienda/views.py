from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.contrib import messages
from core.models import Negocio
from inventario.models import Producto, Categoria, Promo
from pedidos.models import Pedido, PedidoItem, Cliente
from pedidos.emails import enviar_correo_pedido_creado
from django.contrib.auth.models import User  # para crear el usuario
from pedidos.forms import RegistroClienteForm
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt

from .forms import CheckoutForm

# SDK Webpay (Transbank)
try:
    from transbank.webpay.webpay_plus.transaction import Transaction
    from transbank.common.options import WebpayOptions
    from transbank.common.integration_type import IntegrationType
except ImportError:
    Transaction = None  


CART_SESSION_KEY = "carrito"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def get_negocio_actual():
    
    return Negocio.objects.first()


def _get_cart(request):
    """Obtiene el carrito desde la sesión."""
    return request.session.get(CART_SESSION_KEY, {})


def _save_cart(request, cart):
    """Guarda el carrito en la sesión y marca la sesión como modificada."""
    request.session[CART_SESSION_KEY] = cart
    request.session.modified = True


def _build_cart_items(cart_dict):
    """
    Convierte el dict de sesión en una lista de ítems amigable para el template.

    Formato del carrito en sesión:
    {
        "PROD-5": {"cantidad": 2},
        "PROMO-1": {"cantidad": 1},
    }
    """
    items = []
    total = Decimal("0")

    for key, data in cart_dict.items():
        # key -> "PROD-5" o "PROMO-1"
        try:
            tipo, raw_id = key.split("-", 1)
            item_id = int(raw_id)
        except ValueError:
            # Clave malformada, la ignoramos
            continue

        cantidad = int(data.get("cantidad", 0) or 0)
        if cantidad <= 0:
            continue

        # ---------------- Productos normales ----------------
        if tipo == "PROD":
            try:
                producto = Producto.objects.get(pk=item_id, activo=True)
            except Producto.DoesNotExist:
                continue

            stock_disp = max(producto.stock_actual, 0)

            # No sobrepasar stock
            if cantidad > stock_disp:
                cantidad = stock_disp

            if cantidad <= 0:
                continue

            precio_unit = Decimal(producto.precio)
            subtotal = precio_unit * cantidad
            total += subtotal

            items.append({
                "key": key,                     # clave del carrito
                "tipo": "PROD",
                "id": producto.id,
                "producto": producto,
                "nombre": producto.nombre,
                "cantidad": cantidad,
                "precio": precio_unit,
                "precio_unit": precio_unit,
                "subtotal": subtotal,
                "max_cantidad": stock_disp,     # límite para el input
            })

        # ---------------- Promos / Combos ----------------
        elif tipo == "PROMO":
            try:
                promo = Promo.objects.get(pk=item_id, activo=True)
            except Promo.DoesNotExist:
                continue

            # Calculamos cuántos packs se pueden armar según stock
            max_packs = None
            for promo_item in promo.items.select_related("producto"):
                p = promo_item.producto
                stock_p = max(p.stock_actual, 0)
                posible = stock_p // promo_item.cantidad if promo_item.cantidad > 0 else 0
                if max_packs is None:
                    max_packs = posible
                else:
                    max_packs = min(max_packs, posible)

            if max_packs is None:
                max_packs = 0

            if cantidad > max_packs:
                cantidad = max_packs
            if cantidad <= 0:
                continue

            precio_unit = Decimal(promo.precio_combo)
            subtotal = precio_unit * cantidad
            total += subtotal

            items.append({
                "key": key,
                "tipo": "PROMO",
                "id": promo.id,
                "promo": promo,
                "nombre": promo.nombre,
                "cantidad": cantidad,
                "precio": precio_unit,
                "precio_unit": precio_unit,
                "subtotal": subtotal,
                "max_cantidad": max_packs,      # límite para input
            })

    return items, total




def limpiar_carrito_en_session(request):
    """Elimina el carrito de la sesión."""
    if CART_SESSION_KEY in request.session:
        del request.session[CART_SESSION_KEY]
        request.session.modified = True


# ------------------------------------------------------------------
# Vistas de la tienda pública
# ------------------------------------------------------------------


def tienda_home(request):
    negocio = get_negocio_actual()

    categorias_qs = Categoria.objects.filter(
        activo=True,
        negocio=negocio,
    ).order_by("nombre")

    # Promos activas
    promos = Promo.objects.filter(
        activo=True,
        negocio=negocio,
    ).order_by("-id")[:6]

    # Armamos la estructura que el template espera: categoria + algunos productos
    categorias_data = []
    for cat in categorias_qs:
        productos = (
            Producto.objects.filter(
                negocio=negocio,
                activo=True,
                categoria=cat,
            )
            .order_by("nombre")[:4]  # por ejemplo, 4 productos de muestra
        )
        categorias_data.append(
            {
                "categoria": cat,
                "productos": productos,
            }
        )

    # (si más adelante quieres usar productos_destacados, lo agregas aquí)
    context = {
        "negocio": negocio,
        "promos": promos,
        "categorias_data": categorias_data,
    }
    return render(request, "tienda/home.html", context)


def categoria_detalle(request, categoria_id):
    negocio = get_negocio_actual()
    categoria = get_object_or_404(
        Categoria,
        pk=categoria_id,
        activo=True,
        negocio=negocio,
    )

    productos = Producto.objects.filter(
        negocio=negocio,
        activo=True,
        categoria=categoria,
    ).order_by("nombre")

    context = {
        "negocio": negocio,
        "categoria": categoria,
        "productos": productos,
    }
    return render(request, "tienda/producto_lista.html", context)


# ------------------------------------------------------------------
# Carrito
# ------------------------------------------------------------------


@require_POST
def carrito_agregar(request, producto_id):
    negocio = get_negocio_actual()
    producto = get_object_or_404(
        Producto,
        pk=producto_id,
        negocio=negocio,
        activo=True,
    )

    cart = _get_cart(request)
    key = f"PROD-{producto.id}"

    entrada = cart.get(key, {"cantidad": 0})
    entrada["cantidad"] = int(entrada["cantidad"]) + 1
    cart[key] = entrada

    _save_cart(request, cart)
    messages.success(request, f"{producto.nombre} agregado al carrito.")

    next_url = request.META.get("HTTP_REFERER")
    if next_url:
        return redirect(next_url)
    return redirect("tienda:home")


def carrito_eliminar_view(request, item_id):
    cart = _get_cart(request)

    if item_id in cart:
        del cart[item_id]
        _save_cart(request, cart)
        messages.info(request, "Ítem eliminado del carrito.")

    return redirect("tienda:carrito_ver")


@require_POST
def carrito_actualizar(request):
    """
    Actualiza cantidades del carrito.

    Espera inputs con nombre:  cant_<KEY>
    donde KEY es la clave del carrito, ej. "PROD-5" o "PROMO-1".
    """
    cart = _get_cart(request)
    nuevo_cart = {}

    for key, value in request.POST.items():
        if not key.startswith("cant_"):
            continue

        item_key = key.replace("cant_", "", 1).strip()
        if not item_key:
            continue

        # cantidad enviada
        try:
            cantidad = int(value)
        except (ValueError, TypeError):
            continue

        if cantidad <= 0:
            continue

        # clave del carrito -> tipo + id
        try:
            tipo, raw_id = item_key.split("-", 1)
            item_id = int(raw_id)
        except ValueError:
            continue

        # --- Productos normales ---
        if tipo == "PROD":
            try:
                producto = Producto.objects.get(pk=item_id, activo=True)
            except Producto.DoesNotExist:
                continue

            stock_disp = max(producto.stock_actual, 0)
            if stock_disp <= 0:
                continue

            if cantidad > stock_disp:
                cantidad = stock_disp

            nuevo_cart[item_key] = {"cantidad": cantidad}

        # --- Promos / combos ---
        elif tipo == "PROMO":
            try:
                promo = Promo.objects.get(pk=item_id, activo=True)
            except Promo.DoesNotExist:
                continue

            # calculamos packs máximos
            max_packs = None
            for promo_item in promo.items.select_related("producto"):
                p = promo_item.producto
                stock_p = max(p.stock_actual, 0)
                posible = stock_p // promo_item.cantidad if promo_item.cantidad > 0 else 0
                if max_packs is None:
                    max_packs = posible
                else:
                    max_packs = min(max_packs, posible)

            if not max_packs:
                continue

            if cantidad > max_packs:
                cantidad = max_packs

            nuevo_cart[item_key] = {"cantidad": cantidad}

    _save_cart(request, nuevo_cart)

    # ¿Hacia dónde vamos?
    if "go_checkout" in request.POST:
        return redirect("tienda:checkout")
    if "go_shop" in request.POST:
        return redirect("tienda:productos")

    return redirect("tienda:carrito_ver")


def carrito_ver(request):
    negocio = get_negocio_actual()
    cart = _get_cart(request)
    items, total = _build_cart_items(cart)

    context = {
        "negocio": negocio,
        "items": items,
        "total": total,
    }
    return render(request, "tienda/carrito.html", context)


def carrito_vaciar(request):
    limpiar_carrito_en_session(request)
    messages.info(request, "Carrito vaciado.")
    return redirect("tienda:carrito_ver")


# ------------------------------------------------------------------
# Checkout
# ------------------------------------------------------------------


def checkout_view(request):
    negocio = get_negocio_actual()
    cart = _get_cart(request)
    items, total = _build_cart_items(cart)

    if not items:
        messages.warning(request, "Tu carrito está vacío.")
        return redirect("tienda:productos")

    if request.method == "POST":
        form = CheckoutForm(request.POST)

        if form.is_valid():
            datos = form.cleaned_data
            forma_pago = datos["forma_pago"]

            rut = datos.get("rut")
            cliente = None

            if rut:
                cliente, _ = Cliente.objects.get_or_create(
                    negocio=negocio,
                    rut=rut,
                    defaults={
                        "nombre": datos["nombre"],
                        "correo": datos["correo"],
                        "telefono": datos.get("telefono", ""),
                    },
                )
            else:
                if request.user.is_authenticated:
                    cliente = Cliente.objects.filter(
                        negocio=negocio, user=request.user
                    ).first()

            # Crear Pedido
            pedido = Pedido.objects.create(
                negocio=negocio,
                cliente=cliente,
                nombre=datos["nombre"],
                correo=datos["correo"],
                telefono=datos.get("telefono", ""),
                total_monto=total,
                forma_pago=forma_pago,
                estado=Pedido.EST_RECIBIDO,
            )

            # Crear ítems de pedido
            for item in items:
                if item["tipo"] == "PROD":
                    producto = item.get("producto") or Producto.objects.get(
                        pk=item["id"]
                    )
                    PedidoItem.objects.create(
                        pedido=pedido,
                        producto=producto,
                        cantidad=item["cantidad"],
                        precio=item["precio_unit"],
                    )
                elif item["tipo"] == "PROMO":
                    promo = Promo.objects.get(pk=item["id"])
                    for promo_item in promo.items.select_related("producto"):
                        producto = promo_item.producto
                        cantidad_total = promo_item.cantidad * item["cantidad"]
                        PedidoItem.objects.create(
                            pedido=pedido,
                            producto=producto,
                            cantidad=cantidad_total,
                            precio=producto.precio,
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
                    (
                        "Tu pedido ha sido enviado a la botillería. "
                        "Por favor acércate a retirar y pagar en caja."
                    ),
                )
                return redirect("tienda:checkout_exito", pedido_id=pedido.id)

            elif forma_pago == "WEBPAY":
                try:
                    url_pago, token = iniciar_pago_webpay(pedido, request)
                except ValueError as e:
                    messages.error(request, str(e))
                    return redirect("tienda:carrito_ver")

                pedido.webpay_token = token
                pedido.webpay_status = "INICIADO"
                pedido.save(update_fields=["webpay_token", "webpay_status"])

                limpiar_carrito_en_session(request)
                return redirect(f"{url_pago}?token_ws={token}")
            else:
                messages.error(request, "Forma de pago no válida.")
                return redirect("tienda:carrito_ver")
        # Si el form NO es válido: seguimos abajo y volvemos a renderizar
    else:
        # GET: prellenar con datos del usuario autenticado
        initial = {}
        if request.user.is_authenticated:
            cliente = Cliente.objects.filter(
                user=request.user, negocio=negocio
            ).first()

            if cliente:
                initial = {
                    "nombre": cliente.nombre
                    or request.user.get_full_name()
                    or request.user.username,
                    "rut": cliente.rut,
                    "correo": cliente.correo or request.user.email,
                    "telefono": cliente.telefono,
                }

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
    return render(request, "tienda/checkout_exito.html", {"pedido": pedido})


# ------------------------------------------------------------------
# Registro / login clientes
# ------------------------------------------------------------------


def registro_cliente_view(request):
    negocio = get_negocio_actual()

    if request.method == "POST":
        form = RegistroClienteForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            password = form.cleaned_data["password1"]
            email = form.cleaned_data["email"]

            user = User.objects.create_user(
                username=username,
                password=password,
                email=email,
            )

            cliente = form.save(commit=False)
            cliente.negocio = negocio
            cliente.user = user
            cliente.save()

            login(request, user)
            messages.success(
                request, "Cuenta creada y sesión iniciada correctamente."
            )
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
    messages.info(request, "Sesión cerrada.")
    return redirect("tienda:home")


# ------------------------------------------------------------------
# Listado y detalle de productos
# ------------------------------------------------------------------


def productos_list_view(request):
    negocio = get_negocio_actual()
    productos_qs = Producto.objects.filter(
        negocio=negocio,
        activo=True,
    ).order_by("nombre")

    paginator = Paginator(productos_qs, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "negocio": negocio,
        "page_obj": page_obj,
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
    key = f"PROD-{producto.id}"
    cantidad_en_carrito = int(cart.get(key, {}).get("cantidad", 0))

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
            nombre__icontains=q,
        ).order_by("nombre")[:8]

        for p in productos:
            resultados.append(
                {
                    "id": p.id,
                    "nombre": p.nombre,
                    "precio": int(p.precio),
                }
            )

    return JsonResponse({"resultados": resultados})


# ------------------------------------------------------------------
# Webpay
# ------------------------------------------------------------------


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
        integration_type=IntegrationType.TEST,
    )
    tx = Transaction(options)

    buy_order = pedido.codigo
    session_id = str(request.user.id or "anon")
    amount = float(pedido.total_monto or pedido.total)
    return_url = request.build_absolute_uri(
        reverse("tienda:webpay_retorno")
    )

    resp = tx.create(buy_order, session_id, amount, return_url)
    token = resp["token"]
    url = resp["url"]
    return url, token


@csrf_exempt
def webpay_retorno_view(request):
    token = request.GET.get("token_ws") or request.POST.get("token_ws")
    if not token:
        messages.error(request, "No se recibió el token de Webpay.")
        return redirect("tienda:productos")

    if Transaction is None:
        messages.error(request, "El SDK de Transbank no está instalado.")
        return redirect("tienda:productos")

    # Buscar el pedido asociado
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
        pedido.webpay_status = "AUTHORIZED"
        pedido.estado = Pedido.EST_PAGADO
        pedido.save(update_fields=["webpay_status", "estado"])

        enviar_correo_pedido_creado(pedido)
        messages.success(request, "Pago realizado con éxito.")
        return redirect("tienda:checkout_exito", pedido_id=pedido.id)

    else:
        pedido.webpay_status = status or "FAILED"
        pedido.estado = Pedido.EST_CANCELADO
        pedido.liberar_reservas_inventario()
        pedido.save(update_fields=["webpay_status", "estado"])

        messages.error(
            request,
            "El pago fue rechazado o cancelado. Tu pedido ha sido anulado.",
        )
        return redirect("tienda:productos")


# ------------------------------------------------------------------
# Promos / packs
# ------------------------------------------------------------------


def promo_agregar_carrito_view(request, promo_id):
    negocio = get_negocio_actual()
    promo = get_object_or_404(
        Promo,
        pk=promo_id,
        negocio=negocio,
        activo=True,
    )

    cart = _get_cart(request)
    key = f"PROMO-{promo.id}"
    entrada = cart.get(key, {"cantidad": 0})
    entrada["cantidad"] = int(entrada["cantidad"]) + 1
    cart[key] = entrada
    _save_cart(request, cart)

    messages.success(request, f"{promo.nombre} agregado al carrito.")

    next_url = request.META.get("HTTP_REFERER")
    if next_url:
        return redirect(next_url)
    return redirect("tienda:home")
