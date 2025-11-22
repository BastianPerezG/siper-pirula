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
    """
    Crea una venta con form + formset.
    Además envía a la plantilla:
      - PRECIOS: {id_producto: precio}
      - PRODUCTOS_EAN: {ean: id_producto}
    para que el JS pueda:
      * Autocompletar el precio unitario
      * Agregar filas usando la pistola (EAN)
    """
    negocio = request.user.perfilusuario.negocio

    # --- POST: guardar ---
    if request.method == "POST":
        form = VentaForm(request.POST)
        formset = VentaItemFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                # Guardamos cabecera de la venta
                venta = form.save(commit=False)
                venta.negocio = negocio
                venta.save()

                # Guardamos ítems
                items = formset.save(commit=False)
                for item in items:
                    # Si la fila está vacía (sin producto), se ignora
                    if not item.producto:
                        continue

                    item.venta = venta
                    # Por seguridad fijamos el precio desde el producto
                    item.precio_unit = item.producto.precio
                    item.save()

                # Borrar ítems marcados con DELETE (por si en el futuro editas)
                for obj in formset.deleted_objects:
                    obj.delete()

            messages.success(request, "Venta registrada correctamente.")
            return redirect("ventas:venta_detalle", pk=venta.pk)

    # --- GET: mostrar formulario vacío ---
    else:
        form = VentaForm()
        formset = VentaItemFormSet()

    # --- Datos para el JS (precios + EAN) ---
    productos = (
        Producto.objects
        .filter(negocio=negocio, activo=True)
        .order_by("nombre")
    )

    precios = {str(p.id): int(p.precio) for p in productos}
    productos_ean = {str(p.ean): str(p.id) for p in productos if p.ean}

    context = {
        "form": form,
        "formset": formset,
        "precios_json": json.dumps(precios),
        "productos_ean_json": json.dumps(productos_ean),
    }
    return render(request, "ventas/venta_form.html", context)