# inventario/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic import DetailView, CreateView, UpdateView, ListView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.utils.safestring import mark_safe
from .models import Producto, MovimientoInventario, Compra
from .forms import ProductoCrearForm, MovimientoCrearForm, CompraItemFormSet, CompraForm

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
        return redirect(self.get_success_url())


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
