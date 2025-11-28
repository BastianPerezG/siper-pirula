from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django import forms
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

class CheckoutForm(forms.Form):
    nombre = forms.CharField(max_length=120)

    rut = forms.CharField(
        max_length=12,
        required=False,
        validators=[validar_rut],
        help_text="Opcional, pero recomendado para identificar tu pedido.",
    )

    correo = forms.EmailField(required=False)
    telefono = forms.CharField(max_length=40, required=False)

    direccion = forms.CharField(
        max_length=200,
        required=False,
        help_text="Opcional, por ahora el retiro es en local.",
    )

    def __init__(self, *args, **kwargs):
        # truco para saber si viene de usuario logueado
        self.es_usuario = kwargs.pop("es_usuario", False)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        correo = cleaned.get("correo")
        telefono = cleaned.get("telefono")

        # Si NO es usuario logueado, pedimos al menos algún dato de contacto
        if not self.es_usuario and not (correo or telefono):
            raise forms.ValidationError(
                "Debes ingresar al menos un medio de contacto (correo o teléfono)."
            )
        return cleaned


def checkout_view(request):
    negocio = get_negocio_actual()
    items, total = _build_cart_items(request, negocio)

    # Si el carrito está vacío, no tiene sentido seguir
    if not items:
        messages.error(request, "Tu carrito está vacío.")
        return redirect("tienda:carrito_ver")

    # --------- PRELLENAR DATOS SI ESTÁ LOGUEADO ---------
    initial = {}
    if request.user.is_authenticated:
        try:
            cliente = Cliente.objects.get(user=request.user, negocio=negocio)
            initial.update(
                {
                    "nombre": cliente.nombre,
                    "rut": cliente.rut,
                    "correo": cliente.correo,
                    "telefono": cliente.telefono,
                    "direccion": cliente.direccion,
                }
            )
        except Cliente.DoesNotExist:
            # usamos datos del user como base
            initial.update(
                {
                    "nombre": request.user.get_full_name()
                    or request.user.username
                }
            )

    if request.method == "POST":
        form = CheckoutForm(
            request.POST,
            es_usuario=request.user.is_authenticated,
        )

        if form.is_valid():
            nombre = form.cleaned_data["nombre"]
            rut = form.cleaned_data.get("rut")
            correo = form.cleaned_data.get("correo")
            telefono = form.cleaned_data.get("telefono")
            direccion = form.cleaned_data.get("direccion")

            # ------------ VALIDAR STOCK FINAL ANTES DE CREAR PEDIDO ------------
            for it in items:
                producto = it["producto"]
                if it["cantidad"] > producto.stock_actual:
                    messages.error(
                        request,
                        f"Stock insuficiente para {producto.nombre}. "
                        f"Disponible: {producto.stock_actual}",
                    )
                    return redirect("tienda:carrito_ver")

            # ------------ RESOLVER / CREAR CLIENTE ------------
            cliente = None

            if request.user.is_authenticated:
                # Cliente asociado al usuario
                cliente, created = Cliente.objects.get_or_create(
                    negocio=negocio,
                    user=request.user,
                    defaults={
                        "nombre": nombre,
                        "rut": rut,
                        "correo": correo,
                        "telefono": telefono,
                        "direccion": direccion,
                    },
                )
                if not created:
                    cliente.nombre = nombre
                    cliente.rut = rut
                    cliente.correo = correo
                    cliente.telefono = telefono
                    cliente.direccion = direccion
                    cliente.save()
            else:
                # Invitado: intentamos no duplicar tanto por correo o rut
                qs = Cliente.objects.filter(negocio=negocio, activo=True)
                if correo:
                    qs = qs.filter(correo=correo)
                elif rut:
                    qs = qs.filter(rut=rut)
                else:
                    qs = qs.none()

                if qs.exists():
                    cliente = qs.first()
                    cliente.nombre = nombre
                    # completamos datos faltantes sin borrar otros
                    cliente.rut = rut or cliente.rut
                    cliente.correo = correo or cliente.correo
                    cliente.telefono = telefono or cliente.telefono
                    cliente.direccion = direccion or cliente.direccion
                    cliente.save()
                else:
                    cliente = Cliente.objects.create(
                        negocio=negocio,
                        nombre=nombre,
                        rut=rut,
                        correo=correo,
                        telefono=telefono,
                        direccion=direccion,
                    )

            # ------------ CREAR PEDIDO E ITEMS ------------
            pedido = Pedido.objects.create(
                negocio=negocio,
                cliente=cliente,
                nombre=nombre,
                correo=correo,
                telefono=telefono,
            )

            for it in items:
                PedidoItem.objects.create(
                    pedido=pedido,
                    producto=it["producto"],
                    cantidad=it["cantidad"],
                    precio=it["producto"].precio,
                )

            pedido.actualizar_total(guardar=True)
            enviar_correo_pedido_creado(pedido)

            # Vaciar carrito
            _save_cart(request, {})

            messages.success(
                request,
                f"Tu pedido {pedido.codigo} fue creado correctamente.",
            )
            return redirect("tienda:checkout_exito", pedido_id=pedido.id)

    else:
        form = CheckoutForm(
            initial=initial,
            es_usuario=request.user.is_authenticated,
        )

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