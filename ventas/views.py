from django.shortcuts import render, redirect
from django.views.generic import ListView, DetailView
from django.db import transaction
from django.urls import reverse

from .models import Venta
from .forms import VentaForm, VentaItemFormSet


class VentaListaView(ListView):
    model = Venta
    template_name = "ventas/venta_lista.html"
    context_object_name = "ventas"


class VentaDetalleView(DetailView):
    model = Venta
    template_name = "ventas/venta_detalle.html"
    context_object_name = "venta"


def venta_crear_view(request):
    """
    Crear una venta manual (tipo 'venta mostrador simple').
    Más adelante esta lógica la usaremos como base para el POS con lector.
    """
    if request.method == "POST":
        form = VentaForm(request.POST)

        if form.is_valid():
            with transaction.atomic():
                venta = form.save()
                formset = VentaItemFormSet(request.POST, instance=venta)

                if formset.is_valid():
                    formset.save()
                    return redirect("ventas:venta_detalle", pk=venta.pk)
        else:
            formset = VentaItemFormSet(request.POST)
    else:
        form = VentaForm()
        formset = VentaItemFormSet()

    return render(
        request,
        "ventas/venta_crear.html",
        {"form": form, "formset": formset},
    )
