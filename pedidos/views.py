import random
import string

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.db import transaction

from pedidos.emails import enviar_correo_cambio_estado
from .models import Pedido
from .forms import PedidoForm, PedidoItemFormSet
from ventas.models import Venta, VentaItem


def _generar_codigo():
    """Código corto tipo 'AB34XZ'."""
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
    """
    Crear pedidos internos (no web).
    """
    negocio = request.user.perfilusuario.negocio

    if request.method == "POST":
        form = PedidoForm(request.POST, negocio=negocio)
        formset = PedidoItemFormSet(request.POST, form_kwargs={"negocio": negocio})

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                pedido = form.save(commit=False)
                pedido.negocio = negocio

                # Generar código si no viene desde el formulario
                if not pedido.codigo:
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
                    if not item.precio:
                        item.precio = item.producto.precio
                    item.pedido = pedido
                    item.save()
                    items_validos += 1

                # manejar eliminados
                for obj in formset.deleted_objects:
                    obj.delete()

                if items_validos == 0:
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
    """
    Cambia el estado de un pedido y dispara correo de notificación.
    """
    negocio = request.user.perfilusuario.negocio
    pedido = get_object_or_404(Pedido, pk=pk, negocio=negocio)

    if request.method == "POST":
        # Cambiar estado
        pedido.estado = nuevo_estado
        pedido.save(update_fields=["estado"])

        # Notificación por correo
        enviar_correo_cambio_estado(pedido)

        return redirect("pedidos:pedido_detalle", pk=pedido.pk)

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
        return (
            Pedido.objects.filter(
                negocio=negocio,
                estado__in=["RECIBIDO", "PREPARANDO", "LISTO"],
            )
            .order_by("fecha")
        )


@login_required
def pedido_convertir_en_venta_view(request, pk):
    """
    Convierte un pedido en una venta POS cerrada.
    """
    negocio = request.user.perfilusuario.negocio

    pedido = get_object_or_404(
        Pedido,
        pk=pk,
        negocio=negocio,
    )

    # Reglas simples por ahora: no convertir CANCELADO / NO_RETIRA
    if pedido.estado in ["CANCELADO", "NO_RETIRA"]:
        return redirect("pedidos:pedido_detalle", pk=pedido.pk)

    if not pedido.items.exists():
        return redirect("pedidos:pedido_detalle", pk=pedido.pk)

    if request.method == "POST":
        with transaction.atomic():
            venta = Venta.objects.create(
                negocio=negocio,
                doc_tipo=Venta.DOC_BOLETA,
                medio_pago=Venta.MED_EFECTIVO,
                comentario=f"Venta generada desde pedido {pedido.codigo}",
                estado=Venta.EST_CERRADA,
            )

            for p_item in pedido.items.all():
                VentaItem.objects.create(
                    venta=venta,
                    producto=p_item.producto,
                    cantidad=p_item.cantidad,
                    precio_unit=p_item.precio,
                )

            # Marcamos el pedido como RETIRADO (y opcionalmente podrías notificar)
            try:
                pedido.cambiar_estado(pedido.EST_RETIRADO, usuario=request.user)
            except AttributeError:
                pedido.estado = "RETIRADO"
                pedido.save(update_fields=["estado"])

            return redirect("ventas:venta_detalle", pk=venta.pk)

    return render(
        request,
        "pedidos/pedido_convertir_venta_confirmar.html",
        {"pedido": pedido},
    )
