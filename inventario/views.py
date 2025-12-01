# inventario/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic import DetailView, CreateView, UpdateView, ListView, DeleteView,View
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.utils.safestring import mark_safe
from .models import (
    Producto, 
    MovimientoInventario, 
    Compra,Proveedor,
    PlantillaProveedorProducto, 
    Categoria,
    Promo,
    PromoItem,
)

from .forms import (
    ProductoCrearForm, 
    MovimientoCrearForm, 
    CompraItemFormSet, 
    CompraForm,
    PlantillaProveedorProductoForm,
    ProveedorForm,
    PromoForm,
    PromoItemFormSet,
)

import json

# --- SCAN EAN ---

@login_required
def scan_ean(request):
    """
    Lee el EAN desde el input, busca el producto y redirige:
    - si existe -> detalle
    - si no existe -> formulario de creación con EAN precargado
    """
    ean = request.GET.get("ean", "").strip()
    negocio = request.user.perfilusuario.negocio

    if ean:
        try:
            producto = Producto.objects.get(ean=ean, negocio=negocio)
            return redirect("inventario:producto_detalle", pk=producto.pk)
        except Producto.DoesNotExist:
            url = reverse("inventario:producto_crear")
            return redirect(f"{url}?ean={ean}")

    return render(request, "inventario/scan.html")


# --- CBVs para productos ---

class ProductoListaView(LoginRequiredMixin, ListView):
    model = Producto
    template_name = "inventario/productos/producto_lista.html"
    context_object_name = "productos"
    ordering = ["nombre"]
    paginate_by = 25

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return (
            Producto.objects
            .filter(negocio=negocio, activo=True)
            .order_by("nombre")
        )


class ProductoDetalleView(LoginRequiredMixin, DetailView):
    model = Producto
    template_name = "inventario/productos/producto_detalle.html"
    context_object_name = "producto"

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Producto.objects.filter(negocio=negocio)


class ProductoCrearView(LoginRequiredMixin, CreateView):
    model = Producto
    form_class = ProductoCrearForm
    template_name = "inventario/productos/producto_crear.html"
    success_url = reverse_lazy("inventario:scan_ean")

    def get_initial(self):
        initial = super().get_initial()
        ean = self.request.GET.get("ean", "")
        if ean:
            initial["ean"] = ean
        return initial

    def form_valid(self, form):
        producto = form.save(commit=False)
        producto.negocio = self.request.user.perfilusuario.negocio
        producto.save()
        return super().form_valid(form)


class ProductoActualizarView(LoginRequiredMixin, UpdateView):
    model = Producto
    form_class = ProductoCrearForm
    template_name = "inventario/productos/producto_editar.html"
    success_url = reverse_lazy("inventario:scan_ean")

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Producto.objects.filter(negocio=negocio)


# --- Movimientos de stock ---

class MovimientoCrearView(LoginRequiredMixin, CreateView):
    model = MovimientoInventario
    form_class = MovimientoCrearForm
    template_name = "inventario/movimiento_stock/movimiento_crear.html"

    def dispatch(self, request, *args, **kwargs):
        negocio = request.user.perfilusuario.negocio
        self.producto = get_object_or_404(
            Producto,
            pk=kwargs["producto_pk"],
            negocio=negocio,
        )
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.producto = self.producto
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("inventario:producto_detalle", kwargs={"pk": self.producto.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["producto"] = self.producto
        return context


class MovimientoListaView(LoginRequiredMixin, ListView):
    model = MovimientoInventario
    template_name = "inventario/movimiento_stock/movimiento_lista.html"
    context_object_name = "movimientos"
    paginate_by = 25

    def dispatch(self, request, *args, **kwargs):
        negocio = request.user.perfilusuario.negocio
        self.producto = get_object_or_404(
            Producto,
            pk=kwargs["producto_pk"],
            negocio=negocio,
        )
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return self.producto.movimientos.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["producto"] = self.producto
        return context


class ProductoStockCriticoView(LoginRequiredMixin, ListView):
    model = Producto
    template_name = "inventario/movimiento_stock/stock_critico.html"
    context_object_name = "productos"

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        qs = Producto.objects.filter(negocio=negocio, activo=True)
        return [p for p in qs if p.stock_actual < p.stock_min]


# --- Compras a proveedores ---

class CompraListaView(LoginRequiredMixin, ListView):
    model = Compra
    template_name = "inventario/compras/compra_lista.html"
    context_object_name = "compras"

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Compra.objects.filter(negocio=negocio).order_by("-fecha")


class CompraDetalleView(LoginRequiredMixin, DetailView):
    model = Compra
    template_name = "inventario/compras/compra_detalle.html"
    context_object_name = "compra"

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Compra.objects.filter(negocio=negocio)


@login_required
def compra_crear_view(request):
    negocio = request.user.perfilusuario.negocio

    # Mapa de costos y EAN -> id producto
    productos = Producto.objects.filter(negocio=negocio, activo=True)
    costos_map = {str(p.id): p.costo for p in productos}   # ajusta el campo si se llama distinto
    ean_map    = {str(p.ean): str(p.id) for p in productos}

    if request.method == "POST":
        form = CompraForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                compra = form.save(commit=False)
                compra.negocio = negocio
                compra.save()

                formset = CompraItemFormSet(
                    request.POST,
                    instance=compra,
                    form_kwargs={"negocio": negocio},
                )
                if formset.is_valid():
                    formset.save()
                    return redirect("inventario:compra_detalle", pk=compra.pk)
        else:
            formset = CompraItemFormSet(
                request.POST,
                form_kwargs={"negocio": negocio},
            )
    else:
        form = CompraForm()
        formset = CompraItemFormSet(form_kwargs={"negocio": negocio})

    context = {
        "form": form,
        "formset": formset,
        "costos_json": json.dumps(costos_map),
        "ean_map_json": json.dumps(ean_map),
    }
    return render(request, "inventario/compras/compra_crear.html", context)


class CompraEliminarView(LoginRequiredMixin, DeleteView):
    model = Compra
    template_name = "inventario/compras/compra_confirmar_eliminar.html"
    success_url = reverse_lazy("inventario:compra_lista")

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Compra.objects.filter(negocio=negocio)
#==================sebastian-proveedores======================#
#=============================================================#
class ProveedorListView(LoginRequiredMixin, ListView):
    """Muestra la lista de proveedores activos, filtrados por el negocio del usuario."""
    model = Proveedor
    template_name = "inventario/proveedores/proveedor_lista.html"
    context_object_name = 'proveedores'
    ordering = ["nombre"]
    paginate_by = 25
    def get_queryset(self):
        # 1. Obtener el negocio del usuario actual
        negocio = self.request.user.perfilusuario.negocio
        
        # 2. Filtrar por el negocio Y por el estado activo
        return (
            Proveedor.objects
            .filter(negocio=negocio, activo=True)
            .order_by("nombre")
        )
    
    def get_context_data(self, **kwargs):
        # Mantiene la adición de la URL de creación para el template
        context = super().get_context_data(**kwargs)
        context["url_crear_proveedor"] = reverse_lazy("inventario:proveedor_crear")
        return context
    

# ----------------------------------------------------
# B. CREAR PROVEEDOR (CREATE)
# ----------------------------------------------------
class ProveedorCreateView(LoginRequiredMixin, CreateView):
    """Permite crear un nuevo proveedor."""
    model = Proveedor
    form_class = ProveedorForm
    template_name = "inventario/proveedores/proveedor_crear.html" # Template único para crear/editar
    success_url = reverse_lazy("inventario:proveedor_lista") # Redirigir a la lista al éxito

   
    def form_valid(self, form):
        # Asigna automáticamente el negocio del usuario (asumiendo que tu perfil lo tiene)
        form.instance.negocio = self.request.user.perfilusuario.negocio 
        return super().form_valid(form)




# ----------------------------------------------------
# C. ACTUALIZAR PROVEEDOR (UPDATE)
# ----------------------------------------------------
class ProveedorUpdateView(LoginRequiredMixin, UpdateView):
    """Permite editar un proveedor existente."""
    model = Proveedor
    form_class = ProveedorForm
    template_name = "inventario/proveedores/proveedor_editar.html"
    context_object_name = 'proveedor'
    success_url = reverse_lazy("inventario:proveedor_lista")

# ----------------------------------------------------
# D. DETALLE DE PROVEEDOR (DETAIL)
# ----------------------------------------------------

class ProveedorDetailView(LoginRequiredMixin, DetailView):
    """Muestra el detalle de un proveedor específico y su plantilla asociada."""
    model = Proveedor
    template_name = "inventario/proveedores/proveedor_detalle.html" # Nuevo template
    context_object_name = 'proveedor' # El objeto se pasará al template como 'proveedor'

    # Opcional: Sobrescribir get_queryset para asegurar la seguridad por negocio
    def get_queryset(self):
        # Asegura que solo se puedan ver proveedores que pertenezcan al negocio del usuario
        negocio = self.request.user.perfilusuario.negocio
        return Proveedor.objects.filter(negocio=negocio, activo=True)
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        proveedor = self.object # El proveedor actual

        

        # 2. Obtener TODOS los productos del inventario que utilizan este proveedor.
        # Asumiendo que el modelo Producto tiene un ForeignKey a Proveedor llamado 'proveedor'
        context['productos_del_proveedor'] = Producto.objects.filter(
            proveedor=proveedor,
            negocio=self.request.user.perfilusuario.negocio
        ).order_by('nombre')
        
        return context
# ----------------------------------------------------
# E. OCULTAR PROVEEDOR (SOFT DELETE / HIDE)
# ----------------------------------------------------
class ProveedorHideView(LoginRequiredMixin, DeleteView):
    """Cambia el estado del proveedor a inactivo (is_active=False) en lugar de eliminarlo."""
    
    # Redirige a la lista de proveedores
    url = reverse_lazy("inventario:proveedor_lista") 

    def get(self, request, *args, **kwargs):
        try:
            # Obtiene el proveedor a ocultar
            proveedor = Proveedor.objects.get(pk=self.kwargs['pk'])
            
            # Realiza la operación de "ocultar" (Soft Delete)
            proveedor.is_active = False
            proveedor.save()
            
            # Puedes agregar un mensaje de éxito si usas el sistema de mensajes de Django
            # messages.success(request, f"Proveedor '{proveedor.nombre}' ocultado correctamente.")
            
        except Proveedor.DoesNotExist:
            # Puedes agregar un mensaje de error
            # messages.error(request, "El proveedor no existe.")
            pass # Continúa la redirección
            
        return super().get(request, *args, **kwargs)

#=============sebastian-plantilla de proveedores================#

class PlantillaProveedorProductoListView(LoginRequiredMixin, ListView):
    # Modelo CORREGIDO
    model = PlantillaProveedorProducto 
    template_name = "inventario/proveedores/plantilla_lista.html" # Nuevo template
    context_object_name = "plantillas"

    def get_queryset(self):
        # Filtra por proveedor_id de la URL y por negocio del usuario
        proveedor_id = self.kwargs["proveedor_id"]
        negocio = self.request.user.perfilusuario.negocio
        
        return PlantillaProveedorProducto.objects.filter(
            proveedor_id=proveedor_id,
            proveedor__negocio=negocio, # Filtro de seguridad por negocio
            is_active=True
        ).select_related('producto')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Filtra el proveedor por su negocio para evitar acceso a proveedores de otros negocios
        context["proveedor"] = get_object_or_404(
            Proveedor, 
            id=self.kwargs["proveedor_id"], 
            negocio=self.request.user.perfilusuario.negocio
        )
        return context


class PlantillaProveedorProductoCreateView(LoginRequiredMixin, CreateView): # USANDO MIXIN CORREGIDO
    # Modelo CORREGIDO
    model = PlantillaProveedorProducto 
    form_class = PlantillaProveedorProductoForm # Formulario CORREGIDO
    template_name = "inventario/proveedores/form_proveedores.html" # Nuevo template

    def form_valid(self, form):
        # Asegurar que la plantilla se asocia al proveedor correcto de la URL
        proveedor = get_object_or_404(
            Proveedor, 
            id=self.kwargs["proveedor_id"], 
            negocio=self.request.user.perfilusuario.negocio
        )
        form.instance.proveedor = proveedor
        return super().form_valid(form)

    def get_success_url(self):
        return reverse(
            "inventario:proveedor_lista", # Ajustar URL
            kwargs={"proveedor_id": self.kwargs["proveedor_id"]}
        )


class PlantillaProveedorProductoUpdateView(LoginRequiredMixin, UpdateView): # USANDO MIXIN CORREGIDO
    # Modelo CORREGIDO
    model = PlantillaProveedorProducto
    form_class = PlantillaProveedorProductoForm # Formulario CORREGIDO
    template_name = "inventario/proveedores/form_productos_proveedor.html" # Nuevo template

    def get_queryset(self):
        # Asegurar que solo se pueda editar la plantilla de su negocio
        negocio = self.request.user.perfilusuario.negocio
        return PlantillaProveedorProducto.objects.filter(proveedor__negocio=negocio)

    def get_success_url(self):
        # Redirige a la lista de plantillas del proveedor
        return reverse(
            "inventario:plantilla_lista",
            kwargs={"proveedor_id": self.object.proveedor.id}
        )


class PlantillaProveedorProductoHideView(LoginRequiredMixin, View): # USANDO MIXIN CORREGIDO
    def get(self, request, pk):
        negocio = request.user.perfilusuario.negocio
        
        plantilla = get_object_or_404(
            PlantillaProveedorProducto, 
            pk=pk, 
            proveedor__negocio=negocio # Filtro de seguridad
        )
        plantilla.is_active = False
        plantilla.save()
        
        return redirect("inventario:lista_proveedores", proveedor_id=plantilla.proveedor.id)
    

    # En tu views.py para la vista que renderiza esto
class ProveedorProductosView(DetailView): 
    model = Proveedor
    template_name = 'inventario/proveedores/proveedor_detalle.html' # Nuevo template
    context_object_name = 'proveedor'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Asumiendo que 'producto_set' es el related_name del ForeignKey Producto a Proveedor
        context['productos_del_proveedor'] = self.object.producto_set.all() 
        return context
    
# ================== CATEGORÍAS (CRUD INTERNO) ======================

class CategoriaListaView(LoginRequiredMixin, ListView):
    model = Categoria
    template_name = "inventario/categorias/categoria_lista.html"
    context_object_name = "categorias"
    paginate_by = 25

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return (
            Categoria.objects
            .filter(negocio=negocio)
            .order_by("orden", "nombre")
        )


class CategoriaCrearView(LoginRequiredMixin, CreateView):
    model = Categoria
    fields = ["nombre", "imagen", "activa", "orden"]
    template_name = "inventario/categorias/categoria_form.html"
    success_url = reverse_lazy("inventario:categoria_lista")

    def form_valid(self, form):
        form.instance.negocio = self.request.user.perfilusuario.negocio
        return super().form_valid(form)


class CategoriaActualizarView(LoginRequiredMixin, UpdateView):
    model = Categoria
    fields = ["nombre", "imagen", "activa", "orden"]
    template_name = "inventario/categorias/categoria_form.html"
    success_url = reverse_lazy("inventario:categoria_lista")

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Categoria.objects.filter(negocio=negocio)


class CategoriaToggleActivaView(LoginRequiredMixin, View):
    """
    Soft-delete: sólo cambia 'activa' en vez de borrar.
    """
    def post(self, request, pk):
        negocio = request.user.perfilusuario.negocio
        categoria = get_object_or_404(
            Categoria,
            pk=pk,
            negocio=negocio,
        )
        categoria.activa = not categoria.activa
        categoria.save()
        return redirect("inventario:categoria_lista")

# ================== PROMOCIONES / COMBOS ======================

@login_required
def promo_lista_view(request):
    """
    Lista de promociones del negocio actual.
    """
    negocio = request.user.perfilusuario.negocio
    promos = Promo.objects.filter(negocio=negocio).order_by("-activo", "nombre")

    context = {
        "promos": promos,
    }
    return render(request, "inventario/promociones/promo_lista.html", context)


@login_required
def promo_crear_view(request):
    """
    Crear una nueva promo con sus productos (PromoItem).
    """
    negocio = request.user.perfilusuario.negocio

    if request.method == "POST":
        form = PromoForm(request.POST, request.FILES)
        formset = PromoItemFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            promo = form.save(commit=False)
            promo.negocio = negocio
            promo.save()

            formset.instance = promo
            formset.save()

            return redirect("inventario:promo_lista")
    else:
        form = PromoForm()
        formset = PromoItemFormSet()

    context = {
        "modo": "crear",
        "form": form,
        "formset": formset,
    }
    return render(request, "inventario/promociones/promo_form.html", context)


@login_required
def promo_editar_view(request, pk):
    """
    Editar una promo existente y sus productos asociados.
    """
    negocio = request.user.perfilusuario.negocio
    promo = get_object_or_404(Promo, pk=pk, negocio=negocio)

    if request.method == "POST":
        form = PromoForm(request.POST, request.FILES, instance=promo)
        formset = PromoItemFormSet(request.POST, instance=promo)

        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            return redirect("inventario:promo_lista")
    else:
        form = PromoForm(instance=promo)
        formset = PromoItemFormSet(instance=promo)

    context = {
        "modo": "editar",
        "form": form,
        "formset": formset,
        "promo": promo,
    }
    return render(request, "inventario/promociones/promo_form.html", context)


@login_required
def promo_toggle_activa_view(request, pk):
    """
    Soft-delete: cambia 'activo' en vez de borrar la promo.
    """
    negocio = request.user.perfilusuario.negocio
    promo = get_object_or_404(Promo, pk=pk, negocio=negocio)
    promo.activo = not promo.activo
    promo.save(update_fields=["activo"])
    return redirect("inventario:promo_lista")
