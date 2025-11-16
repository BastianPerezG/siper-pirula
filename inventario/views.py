from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic import DetailView, CreateView, UpdateView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Producto, MovimientoInventario
from .forms import ProductoCrearForm, MovimientoCrearForm

def scan_ean(request):
    """
    Lee el EAN desde el input, busca el producto y redirige:
    - si existe -> detalle
    - si no existe -> formulario de creación con EAN precargado
    """
    ean = request.GET.get("ean", "").strip()

    if ean:
        try:
            producto = Producto.objects.get(ean=ean)
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
        # Solo productos activos por defecto
        return Producto.objects.filter(activo=True).order_by("nombre")


class ProductoDetalleView(LoginRequiredMixin, DetailView):
    model = Producto
    template_name = "inventario/productos/producto_detalle.html"
    context_object_name = "producto"


class ProductoCrearView(LoginRequiredMixin, CreateView):
    model = Producto
    form_class = ProductoCrearForm
    template_name = "inventario/productos/producto_crear.html"
    success_url = reverse_lazy("inventario:scan_ean")

    def get_initial(self):
        """
        Precarga el EAN que viene desde el lector (?ean=...).
        """
        initial = super().get_initial()
        ean = self.request.GET.get("ean", "")
        if ean:
            initial["ean"] = ean
        return initial


class ProductoActualizarView(LoginRequiredMixin, UpdateView):
    model = Producto
    form_class = ProductoCrearForm
    template_name = "inventario/productos/producto_editar.html"
    success_url = reverse_lazy("inventario:scan_ean")


# Victas Para Movimientos de Stock

class MovimientoCrearView(LoginRequiredMixin, CreateView):
    model = MovimientoInventario
    form_class = MovimientoCrearForm
    template_name = "inventario/movimiento_stock/movimiento_crear.html"

    def dispatch(self, request, *args, **kwargs):
        # Obtenemos el producto al que se le aplica el movimiento
        self.producto = get_object_or_404(Producto, pk=kwargs["producto_pk"])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        # Asignamos el producto antes de guardar
        form.instance.producto = self.producto
        return super().form_valid(form)

    def get_success_url(self):
        # Al terminar, volvemos a la ficha del producto
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
        self.producto = get_object_or_404(Producto, pk=kwargs["producto_pk"])
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
        # Productos activos con stock actual menor al mínimo
        qs = Producto.objects.filter(activo=True)
        return [p for p in qs if p.stock_actual < p.stock_min]
