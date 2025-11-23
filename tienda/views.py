from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django import forms

from core.models import Negocio
from inventario.models import Producto
from pedidos.models import Pedido, PedidoItem, Cliente

CART_SESSION_KEY = "carrito"


def get_negocio_actual():
    # Para una sola botillería, usamos el primer negocio
    return Negocio.objects.first()


def tienda_home(request):
    """
    Listado público de productos disponibles.
    """
    negocio = get_negocio_actual()
    productos = Producto.objects.filter(
        negocio=negocio,
        activo=True,
    ).order_by("nombre")

    context = {
        "productos": productos,
    }
    return render(request, "tienda/producto_lista.html", context)


def _get_cart(request):
    """
    Obtiene el carrito desde la sesión.
    Estructura: { str(producto_id): cantidad }
    """
    return request.session.get(CART_SESSION_KEY, {})


def _save_cart(request, cart):
    request.session[CART_SESSION_KEY] = cart
    request.session.modified = True


def carrito_agregar(request, producto_id):
    """
    Agrega un producto al carrito (o incrementa cantidad).
    """
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
    """
    Elimina completamente un producto del carrito.
    """
    cart = _get_cart(request)
    pid = str(producto_id)
    if pid in cart:
        del cart[pid]
        _save_cart(request, cart)
    return redirect("tienda:carrito_ver")


def carrito_ver(request):
    """
    Muestra el contenido del carrito.
    """
    negocio = get_negocio_actual()
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

        subtotal = producto.precio * cant
        total += subtotal
        items.append({
            "producto": producto,
            "cantidad": cant,
            "subtotal": subtotal,
        })

    context = {
        "items": items,
        "total": total,
    }
    return render(request, "tienda/carrito.html", context)


# --- Checkout ---


class CheckoutForm(forms.Form):
    nombre = forms.CharField(max_length=120)
    correo = forms.EmailField(required=False)
    telefono = forms.CharField(max_length=40, required=False)


def checkout_view(request):
    negocio = get_negocio_actual()
    cart = _get_cart(request)

    if not cart:
        return redirect("tienda:carrito_ver")

    # construimos items para mostrar en el resumen
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

        subtotal = producto.precio * cant
        total += subtotal
        items.append({
            "producto": producto,
            "cantidad": cant,
            "subtotal": subtotal,
        })

    if request.method == "POST":
        form = CheckoutForm(request.POST)
        if form.is_valid():
            nombre = form.cleaned_data["nombre"]
            correo = form.cleaned_data.get("correo")
            telefono = form.cleaned_data.get("telefono")

            # Buscar o crear Cliente
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
                # estado por defecto: RECIBIDO (lo definimos en el modelo)
            )

            # Crear items
            for it in items:
                PedidoItem.objects.create(
                    pedido=pedido,
                    producto=it["producto"],
                    cantidad=it["cantidad"],
                    precio=it["producto"].precio,
                )

            pedido.actualizar_total(guardar=True)

            # Vaciar carrito
            request.session[CART_SESSION_KEY] = {}
            request.session.modified = True

            return redirect("tienda:checkout_exito", pedido_id=pedido.id)
    else:
        form = CheckoutForm()

    context = {
        "form": form,
        "items": items,
        "total": total,
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
