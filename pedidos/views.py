import random
import string
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from pedidos.emails import enviar_correo_cambio_estado
from .models import Pedido
from .forms import PedidoForm, PedidoItemFormSet
from ventas.models import Venta, VentaItem
from tienda.views import get_negocio_actual

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
                    # ↓↓↓ Reserva de stock en inventario
                    pedido.crear_reservas_inventario()
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
        # Si el pedido se cancela o el cliente no retira, liberamos stock
        if nuevo_estado in ["CANCELADO", "NO_RETIRA"]:
            pedido.liberar_reservas_inventario()

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


@login_required
def pedidos_monitor_view(request):
    negocio = get_negocio_actual()

    # --- ACCIONES POST: cambiar estado desde la tarjeta ---
    if request.method == "POST":
        pedido_id = request.POST.get("pedido_id")
        accion = request.POST.get("accion")

        pedido = get_object_or_404(Pedido, pk=pedido_id, negocio=negocio)

        if accion == "next":
            # “Siguiente” estado lógico
            transiciones = {
                Pedido.EST_RECIBIDO: Pedido.EST_PREPARANDO,
                Pedido.EST_PREPARANDO: Pedido.EST_LISTO,
                Pedido.EST_LISTO: Pedido.EST_RETIRADO,
            }
            nuevo_estado = transiciones.get(pedido.estado)
            if nuevo_estado:
                pedido.cambiar_estado(nuevo_estado, usuario=request.user)
        elif accion == "cancelar":
            pedido.cambiar_estado(Pedido.EST_CANCELADO, usuario=request.user)
        elif accion == "no_retira":
            pedido.cambiar_estado(Pedido.EST_NO_RETIRA, usuario=request.user)

        return redirect("pedidos:pedidos_monitor")  # o el nombre que tengas en urls

    # --- FILTROS GET ---
    estado = request.GET.get("estado", "")
    q = (request.GET.get("q") or "").strip()
    dias = (request.GET.get("dias") or "").strip()

    pedidos = (
        Pedido.objects.filter(negocio=negocio)
        .select_related("cliente")
        .prefetch_related("items__producto")
    )

    # Filtro por estado
    if estado and estado != "TODOS":
        pedidos = pedidos.filter(estado=estado)

    # Filtro por texto (código, nombre, rut, correo)
    if q:
        pedidos = pedidos.filter(
            Q(codigo__icontains=q)
            | Q(nombre__icontains=q)
            | Q(cliente__rut__icontains=q)
            | Q(cliente__nombre__icontains=q)
            | Q(correo__icontains=q)
        )

    # Filtro por últimos N días
    if dias:
        try:
            n = int(dias)
            desde = timezone.now() - timedelta(days=n)
            pedidos = pedidos.filter(fecha__gte=desde)
        except ValueError:
            pass  # si viene basura en dias, lo ignoramos

    pedidos = pedidos.order_by("-fecha")[:60]

    context = {
        "negocio": negocio,
        "pedidos": pedidos,
        "estado": estado,
        "q": q,
        "dias": dias,
        "ESTADO_CHOICES": Pedido.ESTADO_CHOICES,
    }
    return render(request, "pedidos/pedido_cocina.html", context)


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
                pedido=pedido,  # ← vinculación directa
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
                    pedido_item=p_item,  # ← vínculo para reutilizar la reserva
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
