# ventas/views.py

import json
from django.core.serializers.json import DjangoJSONEncoder
from django.shortcuts import render, redirect
from django.views.generic import ListView, DetailView
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Venta
from .forms import VentaForm, VentaItemFormSet
from inventario.models import Producto
from django.db import transaction   


class VentaListaView(LoginRequiredMixin, ListView):
    model = Venta
    template_name = "ventas/venta_lista.html"
    context_object_name = "ventas"
    paginate_by = 25

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Venta.objects.filter(negocio=negocio).order_by("-fecha")


class VentaDetalleView(LoginRequiredMixin, DetailView):
    model = Venta
    template_name = "ventas/venta_detalle.html"
    context_object_name = "venta"

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Venta.objects.filter(negocio=negocio)


@login_required
def venta_crear_view(request):
    """Crear una venta con ítems (POS simple con escáner EAN)."""
    negocio = request.user.perfilusuario.negocio

    # Productos disponibles de este negocio
    productos = Producto.objects.filter(negocio=negocio, activo=True).order_by("nombre")

    # Mapa {id_producto: precio}
    precios = {str(p.id): int(p.precio) for p in productos}

    # Mapa {ean: {id, precio}} para la pistola
    productos_ean = {
        p.ean: {"id": p.id, "precio": int(p.precio)}
        for p in productos
        if p.ean
    }

    if request.method == "POST":
        form = VentaForm(request.POST)
        formset = VentaItemFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                venta = form.save(commit=False)
                venta.negocio = negocio
                venta.save()

                items_validos = 0
                items = formset.save(commit=False)

                for item in items:
                    # Saltar filas vacías o sin producto/cantidad
                    if not item.producto or not item.cantidad or item.cantidad <= 0:
                        continue

                    item.venta = venta
                    # Siempre fijamos el precio desde el producto
                    item.precio_unit = item.producto.precio
                    item.save()
                    items_validos += 1

                # Borrar los marcados para eliminar (en caso de futura edición)
                for obj in formset.deleted_objects:
                    obj.delete()

                # Si no quedó ningún item válido, deshacemos y devolvemos error
                if items_validos == 0:
                    transaction.set_rollback(True)
                    form.add_error(None, "La venta debe tener al menos un producto.")
                else:
                    return redirect("ventas:venta_detalle", pk=venta.pk)
    else:
        form = VentaForm()
        formset = VentaItemFormSet()

    context = {
        "form": form,
        "formset": formset,
        "precios_json": json.dumps(precios),
        "productos_ean_json": json.dumps(productos_ean),
    }
    return render(request, "ventas/venta_form.html", context)