from decimal import Decimal
import logging

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.db.models import Q
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

from core.utils import registrar_bitacora_estructurada


logger = logging.getLogger(__name__)


from .forms import CheckoutForm
from core.models import Negocio
# SDK Webpay (Transbank)
try:
    from transbank.webpay.webpay_plus.transaction import Transaction
    from transbank.common.options import WebpayOptions
    from transbank.common.integration_type import IntegrationType
except ImportError:
    Transaction = None  


CART_SESSION_KEY = "carrito"
AGE_VERIFICATION_SESSION_KEY = "mayor_edad_verificado"


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


def _tiene_productos_con_alcohol(cart_dict):
    """
    Verifica si el carrito contiene productos con alcohol.
    Retorna True si hay al menos un producto con alcohol.
    """
    for key, data in cart_dict.items():
        try:
            tipo, raw_id = key.split("-", 1)
            item_id = int(raw_id)
        except ValueError:
            continue

        if tipo == "PROD":
            try:
                producto = Producto.objects.get(pk=item_id, activo=True)
                if producto.contiene_alcohol:
                    return True
            except Producto.DoesNotExist:
                continue
        elif tipo == "PROMO":
            try:
                promo = Promo.objects.get(pk=item_id, activo=True)
                # Verificar si algún producto de la promo contiene alcohol
                for promo_item in promo.items.select_related("producto"):
                    if promo_item.producto.contiene_alcohol:
                        return True
            except Promo.DoesNotExist:
                continue
    
    return False


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


def verificar_edad_view(request):
    """
    Vista para guardar la verificación de edad en la sesión.
    Si el usuario dice que NO es mayor de edad, se redirige fuera del sitio.
    """
    if request.method == "POST":
        mayor_edad = request.POST.get("mayor_edad")
        
        if mayor_edad == "si":
            request.session[AGE_VERIFICATION_SESSION_KEY] = True
            request.session.modified = True
            messages.success(request, "Verificación de edad completada.")
            # Redirigir a la página de origen o al home
            next_url = request.META.get("HTTP_REFERER") or reverse("tienda:home")
            return redirect(next_url)
        else:
            # Usuario no es mayor de edad
            request.session[AGE_VERIFICATION_SESSION_KEY] = False
            request.session.modified = True
            messages.error(
                request,
                "No es posible continuar. La venta de bebidas alcohólicas es exclusiva para mayores de 18 años."
            )
            # Redirigir fuera del sitio o mostrar mensaje de restricción
            return redirect("tienda:home")
    
    return redirect("tienda:home")


def limpiar_carrito_en_session(request):
    """Elimina el carrito de la sesión."""
    if CART_SESSION_KEY in request.session:
        del request.session[CART_SESSION_KEY]
        request.session.modified = True


# ------------------------------------------------------------------
# Vistas de la tienda pública
# ------------------------------------------------------------------


def tienda_home(request):
    # Ya no redirigimos usuarios internos al dashboard para permitirles ver la tienda
    
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

    productos_qs = Producto.objects.filter(
        negocio=negocio,
        activo=True,
        categoria=categoria,
    ).order_by("nombre")

    # Paginación
    paginator = Paginator(productos_qs, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Obtener todas las categorías para el filtro
    categorias = Categoria.objects.filter(
        negocio=negocio,
        activo=True,
    ).order_by("nombre")

    context = {
        "negocio": negocio,
        "categoria": categoria,
        "productos": page_obj,
        "page_obj": page_obj,
        "categorias": categorias,
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

    # Validar edad si el producto contiene alcohol
    mayor_edad_verificado = request.session.get(AGE_VERIFICATION_SESSION_KEY, False)
    if producto.contiene_alcohol and not mayor_edad_verificado:
        messages.error(
            request,
            "No es posible continuar. La venta de bebidas alcohólicas es exclusiva para mayores de 18 años."
        )
        next_url = request.META.get("HTTP_REFERER")
        if next_url:
            return redirect(next_url)
        return redirect("tienda:home")

    # Obtener cantidad del formulario (por defecto 1)
    cantidad = int(request.POST.get("cantidad", 1))
    if cantidad < 1:
        cantidad = 1

    # Validar stock disponible
    stock_disp = max(producto.stock_actual, 0)
    if stock_disp <= 0:
        messages.error(request, "No hay stock disponible para este producto.")
        next_url = request.META.get("HTTP_REFERER")
        if next_url:
            return redirect(next_url)
        return redirect("tienda:home")

    # Limitar cantidad al stock disponible
    if cantidad > stock_disp:
        cantidad = stock_disp
        messages.warning(request, f"Solo hay {stock_disp} unidad(es) disponible(s).")

    cart = _get_cart(request)
    key = f"PROD-{producto.id}"

    entrada = cart.get(key, {"cantidad": 0})
    entrada["cantidad"] = int(entrada["cantidad"]) + cantidad
    cart[key] = entrada

    _save_cart(request, cart)

    if cantidad == 1:
        messages.success(request, f"{producto.nombre} agregado al carrito.")
    else:
        messages.success(request, f"{cantidad} x {producto.nombre} agregado(s) al carrito.")

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
def carrito_actualizar_item(request):
    """
    Actualiza la cantidad de un item específico del carrito vía AJAX.
    Retorna JSON con el nuevo subtotal y total.
    """
    item_key = request.POST.get("item_key")
    cantidad = request.POST.get("cantidad")

    if not item_key or not cantidad:
        return JsonResponse({"error": "Faltan parámetros"}, status=400)

    try:
        cantidad = int(cantidad)
    except (ValueError, TypeError):
        return JsonResponse({"error": "Cantidad inválida"}, status=400)

    if cantidad <= 0:
        return JsonResponse({"error": "La cantidad debe ser mayor a 0"}, status=400)

    # Parsear la clave del carrito
    try:
        tipo, raw_id = item_key.split("-", 1)
        item_id = int(raw_id)
    except ValueError:
        return JsonResponse({"error": "Clave de item inválida"}, status=400)

    cart = _get_cart(request)

    # --- Productos normales ---
    if tipo == "PROD":
        try:
            producto = Producto.objects.get(pk=item_id, activo=True)
        except Producto.DoesNotExist:
            return JsonResponse({"error": "Producto no encontrado"}, status=404)

        stock_disp = max(producto.stock_actual, 0)
        if stock_disp <= 0:
            return JsonResponse({"error": "Sin stock disponible"}, status=400)

        if cantidad > stock_disp:
            cantidad = stock_disp

        precio_unit = Decimal(producto.precio)
        cart[item_key] = {"cantidad": cantidad}

    # --- Promos / combos ---
    elif tipo == "PROMO":
        try:
            promo = Promo.objects.get(pk=item_id, activo=True)
        except Promo.DoesNotExist:
            return JsonResponse({"error": "Promoción no encontrada"}, status=404)

        # Calcular packs máximos
        max_packs = None
        for promo_item in promo.items.select_related("producto"):
            p = promo_item.producto
            stock_p = max(p.stock_actual, 0)
            posible = stock_p // promo_item.cantidad if promo_item.cantidad > 0 else 0
            if max_packs is None:
                max_packs = posible
            else:
                max_packs = min(max_packs, posible)

        if max_packs is None or max_packs <= 0:
            return JsonResponse({"error": "Sin stock suficiente para esta promoción"}, status=400)

        if cantidad > max_packs:
            cantidad = max_packs

        precio_unit = Decimal(promo.precio_combo)
        cart[item_key] = {"cantidad": cantidad}
    else:
        return JsonResponse({"error": "Tipo de item inválido"}, status=400)

    # Guardar carrito actualizado
    _save_cart(request, cart)

    # Calcular nuevo subtotal y total general
    subtotal = precio_unit * cantidad
    items, total = _build_cart_items(cart)

    return JsonResponse({
        "success": True,
        "subtotal": float(subtotal),
        "total": float(total),
        "cantidad": cantidad,
    })


@require_POST
def carrito_actualizar(request):
    """
    Actualiza cantidades del carrito (usado solo para redirecciones).
    """
    cart = _get_cart(request)
    nuevo_cart = {}

    for key, value in request.POST.items():
        if not key.startswith("cant_"):
            continue

        item_key = key.replace("cant_", "", 1).strip()
        if not item_key:
            continue

        try:
            cantidad = int(value)
        except (ValueError, TypeError):
            continue

        if cantidad <= 0:
            continue

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
    
    # Debug: verificar que el carrito se esté recuperando correctamente
    # Si el carrito está vacío pero debería tener items, podría ser un problema de sesión
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

    # Verificar si hay productos con alcohol en el carrito
    tiene_alcohol = _tiene_productos_con_alcohol(cart)
    
    # Verificar si el usuario ha confirmado ser mayor de edad
    mayor_edad_verificado = request.session.get(AGE_VERIFICATION_SESSION_KEY, False)
    
    # Si hay productos con alcohol y no ha verificado edad, redirigir
    if tiene_alcohol and not mayor_edad_verificado:
        messages.error(
            request,
            "No es posible continuar. La venta de bebidas alcohólicas es exclusiva para mayores de 18 años."
        )
        return redirect("tienda:home")

    if request.method == "POST":
        form = CheckoutForm(request.POST)

        if form.is_valid():
            datos = form.cleaned_data
            forma_pago = datos["forma_pago"]
            
            # Validar checkbox de edad si hay productos con alcohol
            if tiene_alcohol:
                mayor_edad_checkout = datos.get("mayor_edad_checkout", False)
                if not mayor_edad_checkout:
                    form.add_error(
                        "mayor_edad_checkout",
                        "Debes confirmar que eres mayor de 18 años para comprar productos con alcohol."
                    )
                    # Re-renderizar con el error
                    context = {
                        "negocio": negocio,
                        "items": items,
                        "total": total,
                        "form": form,
                        "tiene_alcohol": tiene_alcohol,
                    }
                    return render(request, "tienda/checkout.html", context)

            rut = datos.get("rut")
            cliente = None

            if rut:
                # Usamos update_or_create para manejar clientes existentes y nuevos
                # de forma segura, respetando la restricción UNIQUE(negocio, rut)
                cliente, created = Cliente.objects.update_or_create(
                    negocio=negocio,  # Criterio de búsqueda 1
                    rut=rut,          # Criterio de búsqueda 2
                    defaults={        # Datos a crear o actualizar
                        "nombre": datos["nombre"],
                        "correo": datos["correo"],
                        "telefono": datos.get("telefono", ""),
                        # Si tu modelo Cliente tiene un campo 'user', y el usuario está autenticado, 
                        # puedes asignarlo aquí al crear o actualizar:
                        "user": request.user if request.user.is_authenticated else None,
                    },
                )
            else:
                # Si no hay RUT, intenta buscar el cliente solo si el usuario está autenticado.
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
            productos_y_promos_detalle = []
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
                    productos_y_promos_detalle.append({
                        'tipo_item': 'PRODUCTO',
                        'id': producto.pk,
                        'nombre': producto.nombre,
                        'cantidad': float(item["cantidad"]),
                        'precio_unitario': str(item["precio_unit"]),
                        'subtotal': str(item["subtotal"]),
                    })
                elif item["tipo"] == "PROMO":
                    promo = Promo.objects.get(pk=item["id"])
                    detalle_promo = {
                        'tipo_item': 'PROMOCION',
                        'id': promo.pk,
                        'nombre': promo.nombre,
                        'cantidad': float(item["cantidad"]),
                        'precio_total': str(item["precio_unit"]), # Precio total de la promo
                        'productos_internos': [],
                    }
                    for promo_item in promo.items.select_related("producto"):
                        producto = promo_item.producto
                        cantidad_total = promo_item.cantidad * item["cantidad"]
                        PedidoItem.objects.create(
                            pedido=pedido,
                            producto=producto,
                            cantidad=cantidad_total,
                            precio=producto.precio,
                        )
                        detalle_promo['productos_internos'].append({
                            'id': producto.pk,
                            'nombre': producto.nombre,
                            'cantidad': float(cantidad_total),
                        })
            try:
                # 1. Obtener la instancia de Negocio para la bitácora
                # (Ya la tienes arriba: negocio = get_negocio_actual())
                
                detalles_registro = {
                    'cliente_rut': rut,
                    'forma_pago': forma_pago,
                    'total': str(total), # Convertir Decimal a string
                    'ip_address': request.META.get('REMOTE_ADDR'), 
                    'items_del_pedido': productos_y_promos_detalle,
                }
                
                # 2. Registrar la acción
                registrar_bitacora_estructurada(
                    negocio=request.user.perfilusuario.negocio,
                    usuario=request.user if request.user.is_authenticated else None, # Puede ser Anon
                    nombre_modelo="PedidoOnline",
                    tipo_accion="CREACION_ONLINE",
                    entidad_id=pedido.pk,
                    accion=f"Pedido online N° {pedido.pk} creado exitosamente. Total: ${total}",
                    detalles=detalles_registro
                )
            except NameError as ne:
                # Este error ocurre si la función no está importada
                print(f"ERROR FATAL (IMPORTACIÓN): Bitácora no registrada. {ne}") 
            except Exception as e:
                # Cualquier otro error interno de la función de registro
                print(f"ERROR BITACORA CHECKOUT (INTERNO): {e}") 
            # 🔥 FIN DEL REGISTRO DE BITÁCORA 🔥
            
            # Flujo según forma de pago
            if forma_pago == "RETIRO":
                try:
                    pedido.marcar_pendiente_retiro()
                except Exception as stock_error:
                    # Si falla la reserva de stock, eliminar el pedido y mostrar error
                    pedido.delete()
                    messages.error(request, str(stock_error))
                    return redirect("tienda:carrito_ver")
                # Intentar enviar correo, pero no fallar si hay problemas de configuración SMTP
                try:
                    enviar_correo_pedido_creado(pedido)
                except Exception as e:
                    # Log del error pero no interrumpir el flujo
                    logger.warning(f"Error al enviar correo de confirmación del pedido {pedido.codigo}: {e}")
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
                # Crear reservas de inventario
                try:
                    pedido.crear_reservas_inventario()
                except Exception as stock_error:
                    # Si falla la reserva de stock, eliminar el pedido y mostrar error
                    pedido.delete()
                    messages.error(request, str(stock_error))
                    return redirect("tienda:carrito_ver")
                
                try:
                    url_pago, token = iniciar_pago_webpay(pedido, request)
                except ValueError as e:
                    # Si falla webpay, liberar las reservas y eliminar pedido
                    pedido.liberar_reservas_inventario()
                    pedido.delete()
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
        "tiene_alcohol": tiene_alcohol,
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
# Registro / Login / Perfil
# ------------------------------------------------------------------

from django.contrib.auth.decorators import login_required
from pedidos.forms import RegistroClienteForm, EditarPerfilForm
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm


def registro_cliente_view(request):
    negocio = get_negocio_actual()

    if request.method == "POST":
        form = RegistroClienteForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            password = form.cleaned_data["password1"]

            correo = form.cleaned_data.get("correo", "")


            user = User.objects.create_user(
                username=username,
                password=password,
                email=correo,
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


@login_required(login_url="tienda:login")
def perfil_view(request):
    """
    Dashboard del usuario: muestra sus datos y lista de pedidos.
    """
    negocio = get_negocio_actual()
    # Buscar el cliente asociado al usuario actual
    cliente = Cliente.objects.filter(user=request.user, negocio=negocio).first()

    # Historial de pedidos
    pedidos = []
    if cliente:
        pedidos = Pedido.objects.filter(cliente=cliente).order_by("-fecha")[:20] 

    return render(request, "tienda/perfil.html", {
        "cliente": cliente,
        "pedidos": pedidos
    })


@login_required(login_url="tienda:login")
def perfil_editar_view(request):
    negocio = get_negocio_actual()
    cliente = get_object_or_404(Cliente, user=request.user, negocio=negocio)

    if request.method == "POST":
        # Formulario de datos personales
        form = EditarPerfilForm(request.POST, instance=cliente)
        
        # Formulario de cambio de contraseña
        # Nota: PasswordChangeForm requiere el usuario, no el cliente
        password_form = PasswordChangeForm(request.user, request.POST)

        # Determinar qué se está enviando por el nombre del botón submit o campo hidden
        if "update_profile" in request.POST:
            if form.is_valid():
                # Actualizar email en User también
                new_email = form.cleaned_data["email"]
                if request.user.email != new_email:
                    request.user.email = new_email
                    request.user.save()
                
                form.save()
                messages.success(request, "Tus datos han sido actualizados.")
                return redirect("tienda:perfil")
        
        elif "change_password" in request.POST:
             if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)  # Importante para no desloguear
                messages.success(request, "Tu contraseña ha sido actualizada exitosamente.")
                return redirect("tienda:perfil")
             else:
                 messages.error(request, "Error al cambiar contraseña. Revisa los campos.")

    else:
        form = EditarPerfilForm(instance=cliente, initial={"email": request.user.email})
        password_form = PasswordChangeForm(request.user)

    return render(request, "tienda/perfil_editar.html", {
        "form": form,
        "password_form": password_form
    })


@login_required(login_url="tienda:login")
def pedido_detalle_view(request, pedido_id):
    negocio = get_negocio_actual()
    # Asegúrate de importar Cliente si no está importado, o obtenerlo via user
    cliente = get_object_or_404(Cliente, user=request.user, negocio=negocio)
    
    # Obtener el pedido solo si pertenece al cliente
    pedido = get_object_or_404(Pedido, pk=pedido_id, cliente=cliente)
    
    return render(request, "tienda/pedido_detalle.html", {
        "pedido": pedido,
        "negocio": negocio
    })



# ------------------------------------------------------------------
# Listado y detalle de productos
# ------------------------------------------------------------------


def productos_list_view(request):
    negocio = get_negocio_actual()
    
    # Obtener parámetros de búsqueda y filtro
    q = request.GET.get("q", "").strip()
    categoria_slug = request.GET.get("categoria", "").strip()
    
    # Query base
    productos_qs = Producto.objects.filter(
        negocio=negocio,
        activo=True,
    )
    
    # Filtro por categoría
    categoria = None
    if categoria_slug:
        try:
            categoria = Categoria.objects.get(
                slug=categoria_slug,
                negocio=negocio,
                activo=True
            )
            productos_qs = productos_qs.filter(categoria=categoria)
        except Categoria.DoesNotExist:
            pass
    
    # Filtro por búsqueda mejorada (busca en múltiples campos y por palabras)
    if q:
        # Dividir la búsqueda en palabras individuales
        palabras = q.split()
        
        # Crear un Q object que busque cada palabra en múltiples campos
        query = Q()
        for palabra in palabras:
            # Buscar en nombre, SKU, EAN, formato y unidad de venta
            query |= (
                Q(nombre__icontains=palabra) |
                Q(sku__icontains=palabra) |
                Q(ean__icontains=palabra) |
                Q(formato__icontains=palabra) |
                Q(unidad_de_venta__icontains=palabra)
            )
        
        # También buscar la frase completa (por si alguien busca "vino tinto" exacto)
        query |= (
            Q(nombre__icontains=q) |
            Q(sku__icontains=q) |
            Q(ean__icontains=q) |
            Q(formato__icontains=q) |
            Q(unidad_de_venta__icontains=q)
        )
        
        productos_qs = productos_qs.filter(query).distinct()
    
    # Ordenar
    productos_qs = productos_qs.order_by("nombre")
    
    # Obtener todas las categorías para el filtro
    categorias = Categoria.objects.filter(
        negocio=negocio,
        activo=True,
    ).order_by("nombre")
    
    # Paginación
    paginator = Paginator(productos_qs, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "negocio": negocio,
        "productos": page_obj,  # El template itera sobre page_obj directamente
        "page_obj": page_obj,
        "categorias": categorias,
        "categoria": categoria,
        "q": q,
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
        # Dividir la búsqueda en palabras
        palabras = q.split()
        
        # Crear query mejorada para sugerencias
        query = Q()
        for palabra in palabras:
            query |= (
                Q(nombre__icontains=palabra) |
                Q(sku__icontains=palabra) |
                Q(ean__icontains=palabra) |
                Q(formato__icontains=palabra)
            )
        
        # También buscar la frase completa
        query |= Q(nombre__icontains=q)
        
        productos = Producto.objects.filter(
            negocio=negocio,
            activo=True,
        ).filter(query).distinct().order_by("nombre")[:8]

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
        # Usar el nuevo método que separa los estados
        pedido.estado_pago = Pedido.PAGO_PAGADO
        pedido.estado_preparacion = Pedido.PREP_RECIBIDO  # Listo para preparar
        pedido.estado = Pedido.EST_PAGADO  # Compatibilidad
        pedido.save(update_fields=["webpay_status", "estado_pago", "estado_preparacion", "estado"])

        # Intentar enviar correo, pero no fallar si hay problemas de configuración SMTP
        try:
            enviar_correo_pedido_creado(pedido)
        except Exception as e:
            # Log del error pero no interrumpir el flujo
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Error al enviar correo de confirmación del pedido {pedido.codigo}: {e}")
            # El pedido ya está pagado, así que continuamos normalmente

        messages.success(request, "Pago realizado con éxito.")
        return redirect("tienda:checkout_exito", pedido_id=pedido.id)

    else:
        pedido.webpay_status = status or "FAILED"
        # Marcar como cancelado usando el método actualizado
        pedido.marcar_cancelado_revertir_reserva()

        messages.error(
            request,
            "El pago fue rechazado o cancelado. Tu pedido ha sido anulado.",
        )
        return redirect("tienda:productos")


# ------------------------------------------------------------------
# Promos / packs
# ------------------------------------------------------------------


def promo_detalle(request, promo_id):
    """Vista para mostrar el detalle de una promoción."""
    negocio = get_negocio_actual()
    promo = get_object_or_404(
        Promo,
        pk=promo_id,
        negocio=negocio,
        activo=True,
    )

    # Calcular máximo de packs disponibles según stock
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

    cart = _get_cart(request)
    key = f"PROMO-{promo.id}"
    cantidad_en_carrito = int(cart.get(key, {}).get("cantidad", 0))

    context = {
        "promo": promo,
        "cantidad_en_carrito": cantidad_en_carrito,
        "max_packs": max_packs,
    }
    return render(request, "tienda/promo_detalle.html", context)


@require_POST
def promo_agregar_carrito_view(request, promo_id):
    negocio = get_negocio_actual()
    promo = get_object_or_404(
        Promo,
        pk=promo_id,
        negocio=negocio,
        activo=True,
    )

    # Verificar si la promo contiene productos con alcohol
    tiene_alcohol = False
    for promo_item in promo.items.select_related("producto"):
        if promo_item.producto.contiene_alcohol:
            tiene_alcohol = True
            break

    # Validar edad si la promo contiene alcohol
    mayor_edad_verificado = request.session.get(AGE_VERIFICATION_SESSION_KEY, False)
    if tiene_alcohol and not mayor_edad_verificado:
        messages.error(
            request,
            "No es posible continuar. La venta de bebidas alcohólicas es exclusiva para mayores de 18 años."
        )
        next_url = request.META.get("HTTP_REFERER")
        if next_url:
            return redirect(next_url)
        return redirect("tienda:home")

    # Obtener cantidad del formulario (por defecto 1)
    cantidad = int(request.POST.get("cantidad", 1))
    if cantidad < 1:
        cantidad = 1

    # Calcular máximo de packs disponibles según stock
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

    # Limitar cantidad al máximo disponible
    if cantidad > max_packs:
        cantidad = max_packs
        messages.warning(request, f"Solo hay {max_packs} pack(s) disponible(s).")

    if cantidad <= 0:
        messages.error(request, "No hay stock suficiente para esta promoción.")
        next_url = request.META.get("HTTP_REFERER")
        if next_url:
            return redirect(next_url)
        return redirect("tienda:home")

    cart = _get_cart(request)
    key = f"PROMO-{promo.id}"
    entrada = cart.get(key, {"cantidad": 0})
    entrada["cantidad"] = int(entrada["cantidad"]) + cantidad
    cart[key] = entrada
    _save_cart(request, cart)

    if cantidad == 1:
        messages.success(request, f"{promo.nombre} agregado al carrito.")
    else:
        messages.success(request, f"{cantidad} x {promo.nombre} agregado(s) al carrito.")

    next_url = request.META.get("HTTP_REFERER")
    if next_url:
        return redirect(next_url)
    return redirect("tienda:home")

def terminos(request):
    """
    Vista simple para renderizar la página de Términos y Condiciones.
    """
    return render(request, "tienda/terminos.html")
