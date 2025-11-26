from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django import forms

from core.models import Negocio
from inventario.models import Producto
from pedidos.models import Pedido, PedidoItem, Cliente
from pedidos.emails import enviar_correo_pedido_creado

CART_SESSION_KEY = "carrito"


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


# ------------------------------------------------------------------
# Vistas públicas
# ------------------------------------------------------------------

def tienda_home(request):
    negocio = get_negocio_actual()
    productos = Producto.objects.filter(
        negocio=negocio,
        activo=True,
    ).order_by("nombre")

    return render(
        request,
        "tienda/producto_lista.html",
        {"productos": productos},
    )


def carrito_agregar(request, producto_id):
    negocio = get_negocio_actual()
    producto = get_object_or_404(
        Producto,
        pk=producto_id,
        negocio=negocio,
        activo=True,
    )

    cart = _get_cart(request)
    pid = str(producto.id)
    cart[pid] = cart.get(pid, 0) + 1
    _save_cart(request, cart)

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

    nuevo_cart = {}

    for key, value in request.POST.items():
        if not key.startswith("cant_"):
            continue

        pid = key.replace("cant_", "").strip()

        try:
            cantidad = int(value)
        except (ValueError, TypeError):
            cantidad = 0

        if cantidad > 0:
            nuevo_cart[pid] = cantidad

    _save_cart(request, nuevo_cart)

    # ¿A dónde vamos después de actualizar?
    if "go_checkout" in request.POST:
        return redirect("tienda:checkout")

    if "go_home" in request.POST:
        return redirect("tienda:home")

    # fallback: quedarse en el carrito
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

class CheckoutForm(forms.Form):
    nombre = forms.CharField(max_length=120)
    correo = forms.EmailField(required=False)
    telefono = forms.CharField(max_length=40, required=False)


def checkout_view(request):
    negocio = get_negocio_actual()
    items, total = _build_cart_items(request, negocio)

    if not items:
        return redirect("tienda:carrito_ver")

    if request.method == "POST":
        form = CheckoutForm(request.POST)

        if form.is_valid():
            nombre = form.cleaned_data["nombre"]
            correo = form.cleaned_data.get("correo")
            telefono = form.cleaned_data.get("telefono")

            # Buscar o crear cliente (si dejó algún dato de contacto)
            cliente = None
            if correo:
                cliente, _ = Cliente.objects.get_or_create(
                    negocio=negocio,
                    correo=correo,
                    defaults={"nombre": nombre or correo, "telefono": telefono},
                )
            elif telefono:
                cliente, _ = Cliente.objects.get_or_create(
                    negocio=negocio,
                    telefono=telefono,
                    defaults={"nombre": nombre or telefono, "correo": correo},
                )

            # Crear Pedido
            pedido = Pedido.objects.create(
                negocio=negocio,
                cliente=cliente,
                nombre=nombre,
                correo=correo,
                telefono=telefono,
            )

            # Crear ítems del pedido
            for it in items:
                PedidoItem.objects.create(
                    pedido=pedido,
                    producto=it["producto"],
                    cantidad=it["cantidad"],
                    precio=it["producto"].precio,
                )

            pedido.actualizar_total(guardar=True)

            # Notificación por correo al cliente
            enviar_correo_pedido_creado(pedido)

            # Vaciar carrito
            _save_cart(request, {})

            return redirect("tienda:checkout_exito", pedido_id=pedido.id)
    else:
        form = CheckoutForm()

    return render(
        request,
        "tienda/checkout.html",
        {"form": form, "items": items, "total": total},
    )


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
