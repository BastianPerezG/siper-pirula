import random
import string

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.db import transaction

from .models import Pedido
from .forms import PedidoForm, PedidoItemFormSet


def _generar_codigo():
    """Código corto tipo 'AB34XZ'. Puedes ajustarlo si quieres."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


class PedidoListaView(LoginRequiredMixin, ListView):
    model = Pedido
    template_name = "pedidos/pedido_lista.html"
    context_object_name = "pedidos"
    paginate_by = 25

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Pedido.objects.filter(negocio=negocio).order_by("-fecha")


class PedidoDetalleView(LoginRequiredMixin, DetailView):
    model = Pedido
    template_name = "pedidos/pedido_detalle.html"
    context_object_name = "pedido"

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Pedido.objects.filter(negocio=negocio)


@login_required
def pedido_crear_view(request):
    negocio = request.user.perfilusuario.negocio

    if request.method == "POST":
        form = PedidoForm(request.POST, negocio=negocio)
        formset = PedidoItemFormSet(request.POST, form_kwargs={"negocio": negocio})

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                pedido = form.save(commit=False)
                pedido.negocio = negocio

                # Generar código si no viene desde otro lado
                if not pedido.codigo:
                    # aseguramos unicidad simple
                    codigo = _generar_codigo()
                    while Pedido.objects.filter(codigo=codigo).exists():
                        codigo = _generar_codigo()
                    pedido.codigo = codigo

                pedido.save()

                items = formset.save(commit=False)
                items_validos = 0
                for item in items:
                    if not item.producto or not item.cantidad or item.cantidad <= 0:
                        continue
                    # fijar precio desde producto si no viene en el form
                    if not item.precio:
                        item.precio = item.producto.precio
                    item.pedido = pedido
                    item.save()
                    items_validos += 1

                # manejar eliminados
                for obj in formset.deleted_objects:
                    obj.delete()

                if items_validos == 0:
                    # rollback manual
                    transaction.set_rollback(True)
                    form.add_error(None, "El pedido debe tener al menos un producto.")
                else:
                    pedido.actualizar_total(guardar=True)
                    return redirect("pedidos:pedido_detalle", pk=pedido.pk)
    else:
        form = PedidoForm(negocio=negocio)
        formset = PedidoItemFormSet(form_kwargs={"negocio": negocio})

    context = {
        "form": form,
        "formset": formset,
    }
    return render(request, "pedidos/pedido_form.html", context)


@login_required
def pedido_cambiar_estado_view(request, pk, nuevo_estado):
    pedido = get_object_or_404(
        Pedido,
        pk=pk,
        negocio=request.user.perfilusuario.negocio,
    )
    if request.method == "POST":
        pedido.cambiar_estado(nuevo_estado, usuario=request.user)
        return redirect("pedidos:pedido_detalle", pk=pedido.pk)

    # confirmación simple
    return render(
        request,
        "pedidos/pedido_confirmar_estado.html",
        {"pedido": pedido, "nuevo_estado": nuevo_estado},
    )


class PedidoCocinaView(LoginRequiredMixin, ListView):
    model = Pedido
    template_name = "pedidos/pedido_cocina.html"
    context_object_name = "pedidos"

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Pedido.objects.filter(
            negocio=negocio,
            estado__in=["RECIBIDO", "PREPARANDO", "LISTO"],
        ).order_by("fecha")