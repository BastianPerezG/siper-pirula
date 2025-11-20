from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, DetailView
from django.views import View
from django.db import transaction
from django.urls import reverse

from inventario.models import Producto, MovimientoInventario
from .models import Venta
from .forms import VentaForm, VentaItemFormSet

import json

class VentaListaView(ListView):
    model = Venta
    template_name = "ventas/venta_lista.html"
    context_object_name = "ventas"


class VentaDetalleView(DetailView):
    model = Venta
    template_name = "ventas/venta_detalle.html"
    context_object_name = "venta"


class VentaCreateView(View):

    def _build_precios_json(self):
        """
        Crea un dict {id_producto: precio} para usar en el JS.
        """
        productos = Producto.objects.filter(activo=True).values("id", "precio")
        mapa = {str(p["id"]): p["precio"] for p in productos}
        return json.dumps(mapa)

    def get(self, request):
        form = VentaForm()
        # IMPORTANTE: usar un prefix fijo para el formset
        formset = VentaItemFormSet(prefix="items")

        context = {
            "form": form,
            "formset": formset,
            "precios_json": self._build_precios_json(),
        }
        return render(request, "ventas/venta_form.html", context)

    def post(self, request):
        form = VentaForm(request.POST)
        formset = VentaItemFormSet(request.POST, prefix="items")

        context = {
            "form": form,
            "formset": formset,
            "precios_json": self._build_precios_json(),
        }

        if form.is_valid() and formset.is_valid():
            venta = form.save()

            items = formset.save(commit=False)
            for item in items:
                # Si la fila está vacía (sin producto), la saltamos
                if not item.producto:
                    continue
                item.venta = venta
                # Seguridad: fijar precio desde el producto
                item.precio_unit = item.producto.precio
                item.save()

            # Por si algún día editáramos ventas
            for obj in formset.deleted_objects:
                obj.delete()

            return redirect("ventas:venta_detalle", pk=venta.pk)

        # Si hay errores, volvemos a mostrar el formulario
        return render(request, "ventas/venta_form.html", context)

