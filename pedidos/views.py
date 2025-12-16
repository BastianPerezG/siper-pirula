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

from core.utils import registrar_bitacora_estructurada
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
    estado_anterior = pedido.estado
    stock_liberado = False
    if request.method == "POST":
        comentario_usuario = request.POST.get('comentario_bitacora','').strip()
        # Si el pedido se cancela o el cliente no retira, liberamos stock
        if nuevo_estado in ["CANCELADO", "NO_RETIRA"]:
            pedido.liberar_reservas_inventario()
            stock_liberado = True
        # Cambiar estado
        pedido.estado = nuevo_estado
        pedido.save(update_fields=["estado"])

        #Capturar y registrar
        accion_descripcion = f"Cambio del estado del pedido#{pedido.pk}:{estado_anterior}->{nuevo_estado}"
        #Preparamos los detalles criticos del Json
        detalles_del_registro = {
            'pedido_codigo': pedido.codigo,
            'estado_anterior': estado_anterior,
            'nuevo_estado': nuevo_estado,
        }
        if comentario_usuario:
            detalles_del_registro['comentario_usuario'] = comentario_usuario
        if stock_liberado:
            if nuevo_estado == "CANCELADO":
                mensaje_reversa = "Stock liberado por cancelación."
            elif nuevo_estado == "NO_RETIRA":
                mensaje_reversa = "Stock liberado porque el cliente no retiro el pedido."
            else:
                mensaje_reversa = "Reserva de stock liberado(Motivo no especificado)."
            
            detalles_del_registro['accion_inventario'] = mensaje_reversa
        
        # Llamada a la función de registro con TODOS los argumentos requeridos
        try:
            registrar_bitacora_estructurada(
                negocio=negocio,
                usuario=request.user,
                tipo_accion='CAMBIO_ESTADO',
                nombre_modelo='PedidoOnline',
                accion=accion_descripcion,
                entidad_id=pedido.pk,
                detalles=detalles_del_registro
            )
        except Exception as e:
            # Si falla el registro de bitácora, solo lo registramos pero no detenemos el flujo
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error al registrar bitácora para pedido {pedido.codigo}: {str(e)}")
        
        # Notificación por correo
        try:
            enviar_correo_cambio_estado(pedido)
        except Exception as e:
            # Si falla el correo, continuamos
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Error al enviar correo para pedido {pedido.codigo}: {str(e)}")

        return redirect("pedidos:pedido_detalle", pk=pedido.pk)

    return render(
        request,
        "pedidos/pedido_confirmar_estado.html",
        {"pedido": pedido, "nuevo_estado": nuevo_estado},
    )


@login_required
def pedidos_monitor_view(request):
    from django.contrib import messages
    import logging
    logger = logging.getLogger(__name__)
    
    negocio = get_negocio_actual()

    # --- ACCIONES POST: cambiar estado desde la tarjeta ---
    if request.method == "POST":
        pedido_id = request.POST.get("pedido_id")
        accion = request.POST.get("accion")

        pedido = get_object_or_404(Pedido, pk=pedido_id, negocio=negocio)
        estado_anterior = pedido.estado_preparacion
        pago_anterior = pedido.estado_pago

        try:
            if accion == "next":
                # "Siguiente" estado lógico basado en estado_preparacion
                transiciones = {
                    Pedido.PREP_RECIBIDO: Pedido.PREP_PREPARANDO,
                    Pedido.PREP_PREPARANDO: Pedido.PREP_LISTO,
                    Pedido.PREP_LISTO: Pedido.PREP_RETIRADO,
                }
                nuevo_estado = transiciones.get(pedido.estado_preparacion)
                if nuevo_estado:
                    pedido.cambiar_estado_preparacion(nuevo_estado, usuario=request.user)
                    messages.success(request, f"Pedido {pedido.codigo} actualizado a {pedido.get_estado_preparacion_display()}")
                    
                    # Registrar en bitácora
                    try:
                        registrar_bitacora_estructurada(
                            negocio=negocio,
                            usuario=request.user,
                            tipo_accion='CAMBIO_ESTADO_PREPARACION',
                            nombre_modelo='PedidoOnline',
                            accion=f"Pedido #{pedido.codigo} cambio de estado: {estado_anterior} → {nuevo_estado}",
                            entidad_id=pedido.pk,
                            detalles={
                                'pedido_codigo': pedido.codigo,
                                'estado_preparacion_anterior': estado_anterior,
                                'estado_preparacion_nuevo': nuevo_estado,
                                'estado_pago': pedido.estado_pago,
                                'origen': 'monitor_cocina'
                            }
                        )
                    except Exception as e:
                        logger.error(f"Error al registrar bitácora: {str(e)}")
                else:
                    messages.warning(request, f"No se puede avanzar el pedido {pedido.codigo}")
                    
            elif accion == "cancelar":
                pedido.marcar_cancelado_revertir_reserva(usuario=request.user)
                messages.warning(request, f"Pedido {pedido.codigo} cancelado")
                
                # Registrar en bitácora
                try:
                    registrar_bitacora_estructurada(
                        negocio=negocio,
                        usuario=request.user,
                        tipo_accion='CANCELACION_PEDIDO',
                        nombre_modelo='PedidoOnline',
                        accion=f"Pedido #{pedido.codigo} CANCELADO con reversión de stock",
                        entidad_id=pedido.pk,
                        detalles={
                            'pedido_codigo': pedido.codigo,
                            'estado_preparacion_anterior': estado_anterior,
                            'estado_pago_anterior': pago_anterior,
                            'accion_inventario': 'Stock liberado por cancelación',
                            'origen': 'monitor_cocina'
                        }
                    )
                except Exception as e:
                    logger.error(f"Error al registrar bitácora: {str(e)}")
                
            elif accion == "no_retira":
                # Marcar como no retira (liberar stock)
                pedido.estado_preparacion = Pedido.PREP_NO_RETIRA
                pedido.liberar_reservas_inventario()
                pedido.save(update_fields=["estado_preparacion"])
                messages.warning(request, f"Pedido {pedido.codigo} marcado como No Retira")
                
                # Registrar en bitácora
                try:
                    registrar_bitacora_estructurada(
                        negocio=negocio,
                        usuario=request.user,
                        tipo_accion='NO_RETIRA_PEDIDO',
                        nombre_modelo='PedidoOnline',
                        accion=f"Pedido #{pedido.codigo} marcado como NO RETIRA con reversión de stock",
                        entidad_id=pedido.pk,
                        detalles={
                            'pedido_codigo': pedido.codigo,
                            'estado_preparacion_anterior': estado_anterior,
                            'estado_pago': pedido.estado_pago,
                            'accion_inventario': 'Stock liberado porque cliente no retiró',
                            'origen': 'monitor_cocina'
                        }
                    )
                except Exception as e:
                    logger.error(f"Error al registrar bitácora: {str(e)}")
        
        except Exception as e:
            # Si falla el envío de correo u otra cosa, registramos el error pero continuamos
            logger.error(f"Error al procesar acción {accion} en pedido {pedido.codigo}: {str(e)}")
            # Incluso si falla el correo, mostramos que la acción se intentó
            messages.info(request, f"Acción ejecutada (nota: el correo de notificación podría no haberse enviado)")

        return redirect("pedidos:pedidos_monitor")

    # --- FILTROS GET ---
    estado_prep = request.GET.get("estado", "")
    q = (request.GET.get("q") or "").strip()
    dias = (request.GET.get("dias") or "").strip()
    mostrar_finalizados = request.GET.get("finalizados", "") == "si"

    pedidos = (
        Pedido.objects.filter(negocio=negocio)
        .select_related("cliente")
        .prefetch_related("items__producto")
    )

    # Filtro por estado de preparación
    if estado_prep and estado_prep != "TODOS":
        pedidos = pedidos.filter(estado_preparacion=estado_prep)
    elif not mostrar_finalizados:
        # Por defecto, excluir pedidos finalizados (retirados, cancelados, no retira)
        pedidos = pedidos.exclude(
            estado_preparacion__in=[
                Pedido.PREP_RETIRADO,
                Pedido.PREP_CANCELADO,
                Pedido.PREP_NO_RETIRA
            ]
        )

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
            pass

    # IMPORTANTE: Calcular estadísticas ANTES del slice
    stats = {
        'recibidos': pedidos.filter(estado_preparacion=Pedido.PREP_RECIBIDO).count(),
        'preparando': pedidos.filter(estado_preparacion=Pedido.PREP_PREPARANDO).count(),
        'listos': pedidos.filter(estado_preparacion=Pedido.PREP_LISTO).count(),
    }

    # Ahora sí, limitar y ordenar
    pedidos = pedidos.order_by("-fecha")[:60]

    context = {
        "negocio": negocio,
        "pedidos": pedidos,
        "estado": estado_prep,
        "q": q,
        "dias": dias,
        "mostrar_finalizados": mostrar_finalizados,
        "stats": stats,
        "ESTADO_PREPARACION_CHOICES": Pedido.ESTADO_PREPARACION_CHOICES,
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
        import logging
        logger = logging.getLogger(__name__)
        
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
            # Agregamos manejo de errores para SMTP
            try:
                pedido.cambiar_estado(pedido.EST_RETIRADO, usuario=request.user)
            except AttributeError:
                # Fallback si no existe el método
                pedido.estado = "RETIRADO"
                pedido.save(update_fields=["estado"])
            except Exception as e:
                # Si falla el envío de correo, solo registramos el error
                logger.warning(f"Error al cambiar estado o enviar correo para pedido {pedido.codigo}: {str(e)}")
                # Actualizar el estado manualmente
                pedido.estado = "RETIRADO"
                pedido.save(update_fields=["estado"])

            return redirect("ventas:venta_detalle", pk=venta.pk)

    return render(
        request,
        "pedidos/pedido_convertir_venta_confirmar.html",
        {"pedido": pedido},
    )
