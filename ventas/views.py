# ventas/views.py

from django.core.serializers.json import DjangoJSONEncoder
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, DetailView
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import Venta,VentaItem,Anulacion, CajaTurno, ArqueoParcial
from .forms import VentaForm, VentaItemFormSet, AperturaCajaForm, ArqueoParcialForm, CierreCajaForm
from inventario.models import Producto, MovimientoInventario
from django.db import transaction   
from core.utils import registrar_bitacora_simple
from core.models import Negocio, PerfilUsuario
from django.db.models import Sum, F, DecimalField, ExpressionWrapper

# Imports para el PDF
from django.template.loader import render_to_string
from django.http import HttpResponse
from xhtml2pdf import pisa


import json # Necesario para json.dumps en el contexto

def _caja_abierta(negocio):
    """
    Devuelve la caja abierta del negocio o None.
    """
    return CajaTurno.objects.filter(
        negocio=negocio,
        estado=CajaTurno.EST_ABIERTA,
    ).first()


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

    caja = _caja_abierta(negocio)
    if not caja:
        messages.error(
            request,
            "No puedes registrar ventas porque no hay una caja abierta. "
            "Abre caja primero."
        )
        return redirect("ventas:caja_apertura")
    
    productos = Producto.objects.filter(negocio=negocio, activo=True).order_by("nombre")
    precios = {str(p.id): int(p.precio) for p in productos}
    productos_ean = {
        p.ean: {"id": p.id, "precio": int(p.precio)}
        for p in productos
        if p.ean
    }

    if request.method == "POST":
        form = VentaForm(request.POST)
        formset = VentaItemFormSet(request.POST, form_kwargs={"negocio": negocio, "usuario": request.user})
        accion = request.POST.get("accion", "cerrar")

        if form.is_valid() and formset.is_valid():
            comentario_usuario = (form.cleaned_data.get("comentario") or "").strip()

            with transaction.atomic():
                venta = form.save(commit=False)
                venta.negocio = negocio
                venta.estado = (
                    Venta.EST_ABIERTA if accion == "espera" else Venta.EST_CERRADA
                )
                venta.save()

                items_validos = 0
                items = formset.save(commit=False)

                for item in items:
                    if not item.producto or not item.cantidad or item.cantidad <= 0:
                        continue

                    item.venta = venta
                    item.precio_unit = item.producto.precio
                    item.save()
                    items_validos += 1

                for obj in formset.deleted_objects:
                    obj.delete()

                if items_validos == 0:
                    transaction.set_rollback(True)
                    form.add_error(None, "La venta debe tener al menos un producto.")
                else:
                    venta.monto_total = venta.total
                    venta.save(update_fields=["monto_total", "estado"])

                    detalles_registro = {
                        "items_vendidos": items_validos,
                        "monto_total": str(venta.monto_total),
                        "estado": venta.estado,
                    }
                    if comentario_usuario:
                        detalles_registro["comentario_usuario"] = comentario_usuario

                    registrar_bitacora_simple(
                        usuario=request.user,
                        accion=f"Creación de Venta POS #{venta.pk}",
                        entidad_id=venta.pk,
                        detalles=detalles_registro,
                    )

                    if accion == "espera":
                        messages.success(
                            request,
                            f"Venta #{venta.pk} enviada a espera correctamente.",
                        )
                        return redirect("ventas:ventas_en_espera_lista")
                    else:
                        messages.success(
                            request,
                            f"Venta #{venta.pk} creada y cerrada correctamente.",
                        )
                        return redirect("ventas:venta_detalle", pk=venta.pk)
    else:
        form = VentaForm()
        formset = VentaItemFormSet(form_kwargs={"negocio": negocio, "usuario": request.user})

    context = {
        "form": form,
        "formset": formset,
        "precios_json": json.dumps(precios),
        "productos_ean_json": json.dumps(productos_ean),
    }
    return render(request, "ventas/venta_form.html", context)


@login_required
def venta_editar_view(request, pk):
    """
    Editar una venta en estado ABIERTA (en espera).

    Permite:
    - Cambiar datos generales (doc_tipo, medio_pago, comentario).
    - Agregar / quitar productos.
    - Cambiar cantidades.

    No permite:
    - Editar ventas cerradas o anuladas.
    - Editar ventas que vienen de pedidos (para no romper reservas de pedidos).
    """
    negocio = request.user.perfilusuario.negocio
    venta = get_object_or_404(Venta, pk=pk, negocio=negocio)

    # Solo se editan ventas en espera
    if venta.estado != Venta.EST_ABIERTA:
        messages.error(request, "Solo se pueden editar ventas que estén en espera.")
        return redirect("ventas:venta_detalle", pk=venta.pk)

    # Ventas provenientes de pedidos se mantienen fijas (prudente)
    if venta.items.filter(pedido_item__isnull=False).exists():
        messages.error(
            request,
            "No es posible editar ventas generadas desde un pedido. "
            "Debe anular la venta y volver a generar el flujo.",
        )
        return redirect("ventas:venta_detalle", pk=venta.pk)

    # Productos disponibles de este negocio (para el POS)
    productos = Producto.objects.filter(
        negocio=negocio, activo=True
    ).order_by("nombre")
    precios = {str(p.id): int(p.precio) for p in productos}
    productos_ean = {
        p.ean: {"id": p.id, "precio": int(p.precio)}
        for p in productos
        if p.ean
    }

    if request.method == "POST":
        form = VentaForm(request.POST, instance=venta)
        formset = VentaItemFormSet(
            request.POST,
            instance=venta,
            form_kwargs={"negocio": negocio, "usuario": request.user},
        )

        # Por defecto, si no viene nada, la dejamos en espera
        accion = request.POST.get("accion", "espera")

        if form.is_valid() and formset.is_valid():
            comentario_usuario = (form.cleaned_data.get("comentario") or "").strip()

            with transaction.atomic():
                # 1) Actualizamos datos generales de la venta
                venta = form.save(commit=False)
                venta.negocio = negocio
                venta.estado = (
                    Venta.EST_ABIERTA if accion == "espera" else Venta.EST_CERRADA
                )
                venta.save()

                # 2) Eliminamos TODOS los movimientos de inventario de esta venta
                MovimientoInventario.objects.filter(venta_item__venta=venta).delete()

                # 3) Eliminamos TODOS los ítems actuales de la venta
                venta.items.all().delete()

                # 4) Recreamos los ítems desde el formset
                items_validos = 0
                for item_form in formset:
                    if not item_form.cleaned_data:
                        continue
                    if item_form.cleaned_data.get("DELETE"):
                        continue

                    item = item_form.save(commit=False)

                    # Saltar filas vacías o sin datos suficientes
                    if not item.producto or not item.cantidad or item.cantidad <= 0:
                        continue

                    item.venta = venta
                    item.precio_unit = item.producto.precio
                    item.save()
                    items_validos += 1

                if items_validos == 0:
                    # Si no quedó ningún ítem, revertimos todo
                    transaction.set_rollback(True)
                    form.add_error(
                        None,
                        "La venta debe tener al menos un producto válido.",
                    )
                else:
                    # 5) Actualizamos total y registramos en bitácora
                    venta.monto_total = venta.total
                    venta.save(update_fields=["monto_total", "estado"])

                    detalles_registro = {
                        "items_vendidos": items_validos,
                        "monto_total": str(venta.monto_total),
                        "estado": venta.estado,
                        "tipo_operacion": "Edición de venta en espera (reemplazo de ítems)",
                    }
                    if comentario_usuario:
                        detalles_registro["comentario_usuario"] = comentario_usuario

                    registrar_bitacora_simple(
                        usuario=request.user,
                        accion=f"Edición de Venta #{venta.pk}",
                        entidad_id=venta.pk,
                        detalles=detalles_registro,
                    )

                    if accion == "espera":
                        messages.success(
                            request,
                            f"Venta #{venta.pk} actualizada y mantenida en espera.",
                        )
                        return redirect("ventas:ventas_en_espera_lista")
                    else:
                        messages.success(
                            request,
                            f"Venta #{venta.pk} actualizada y cerrada correctamente.",
                        )
                        return redirect("ventas:venta_detalle", pk=venta.pk)

        # Si llega aquí es que form o formset no son válidos
        messages.error(
            request,
            "Revisa los datos de la venta. Hay errores en el formulario.",
        )
    else:
        form = VentaForm(instance=venta)
        formset = VentaItemFormSet(
            instance=venta,
            form_kwargs={"negocio": negocio, "usuario": request.user},
        )

    context = {
        "form": form,
        "formset": formset,
        "precios_json": json.dumps(precios),
        "productos_ean_json": json.dumps(productos_ean),
        "venta": venta,
        "modo_edicion": True,
    }
    return render(request, "ventas/venta_form.html", context)


class VentaEnEsperaListaView(LoginRequiredMixin, ListView):
    """
    Lista de ventas en estado 'En espera', para que la caja pueda seleccionarlas
    y proceder al cobro/cierre.
    """
    model = Venta
    template_name = "ventas/venta_espera_lista.html"
    context_object_name = "ventas_en_espera"
    paginate_by = 25

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return (
            Venta.objects
            .filter(negocio=negocio, estado=Venta.EST_ABIERTA)
            .order_by("fecha")
        )

@login_required
def venta_cobrar_view(request, pk):
    """
    Cobra (cierra) una venta en espera:
    - Convierte las reservas en salidas.
    - Marca la venta como CERRADA.
    """
    negocio = request.user.perfilusuario.negocio
    venta = get_object_or_404(Venta, pk=pk, negocio=negocio)

    if venta.estado != Venta.EST_ABIERTA:
        messages.error(request, "Solo se pueden cobrar ventas que estén en espera.")
        return redirect("ventas:venta_detalle", pk=venta.pk)

    if request.method == "POST":
        with transaction.atomic():
            venta.cerrar_y_actualizar_stock()

            registrar_bitacora_simple(
                usuario=request.user,
                accion=f"Cobro y cierre de Venta en espera #{venta.pk}",
                entidad_id=venta.pk,
                detalles={
                    "monto_total": str(venta.monto_total),
                    "estado_anterior": Venta.EST_ABIERTA,
                    "estado_nuevo": Venta.EST_CERRADA,
                },
            )

        messages.success(request, f"Venta #{venta.pk} cobrada y cerrada correctamente.")
        return redirect("ventas:venta_detalle", pk=venta.pk)

    return render(request, "ventas/venta_cobrar_confirmacion.html", {"venta": venta})


@login_required
def venta_anular_view(request, pk):
    venta = get_object_or_404(Venta, pk=pk, negocio=request.user.perfilusuario.negocio)
    
    # Prevenir doble anulación
    if venta.estado == Venta.EST_ANULADA:
        messages.error(request, "Esta venta ya fue anulada.")
        return redirect('ventas:venta_detalle', pk=pk)

    if request.method == 'POST':
        motivo = request.POST.get('motivo')
        
        if not motivo:
            messages.error(request, "Debe especificar un motivo para la anulación.")
            return render(request, 'ventas/venta_anular_confirmacion.html', {'venta': venta})
            
        with transaction.atomic():
            # 1. Crear el registro de Anulacion (VentaItem es None, como se requiere)
            anulacion = Anulacion.objects.create(
                venta=venta,
                motivo=motivo,
                usuario=request.user,
                venta_item=None # Clave para anulación completa
            )

            # 2. Revertir el stock y eliminar items lógicos (o simplemente revertir stock)
            for item in venta.items.all():
                # Crear un movimiento de ENTRADA para devolver el stock
                MovimientoInventario.objects.create(
                    producto=item.producto,
                    tipo=MovimientoInventario.TIPO_ENTRADA,
                    cantidad=item.cantidad,
                    comentario=f"Reversa por Anulación Total Venta #{venta.pk} (Motivo: {motivo})",
                    # Puedes relacionar esto a la Anulacion si quieres:
                    # anulacion=anulacion 
                )

            # 3. Actualizar el estado de la Venta
            venta.estado = Venta.EST_ANULADA
            venta.save(update_fields=['estado'])
            
            # 4. Registrar la Bitácora
            detalles_registro = {
                'motivo_anulacion': motivo,
                'monto_original': str(venta.monto_total),
                'items_revertidos': venta.items.count(),
                'usuario_anulador_id': str(request.user.pk),
            }
            registrar_bitacora_simple(
                usuario=request.user,
                accion=f"Anulación completa de Venta POS #{venta.pk}",
                entidad_id=venta.pk,
                detalles=detalles_registro
            )

            messages.success(request, f"Venta #{venta.pk} anulada y stock revertido correctamente.")
            return redirect('ventas:venta_detalle', pk=pk)

    return render(request, 'ventas/venta_anular_confirmacion.html', {'venta': venta})


@login_required
def caja_apertura_view(request):
    negocio = request.user.perfilusuario.negocio

    if _caja_abierta(negocio):
        messages.info(request, "Ya existe una caja abierta para este negocio.")
        return redirect("ventas:venta_lista")

    if request.method == "POST":
        form = AperturaCajaForm(request.POST)
        if form.is_valid():
            caja = form.save(commit=False)
            caja.negocio = negocio
            caja.usuario_apertura = request.user
            caja.estado = CajaTurno.EST_ABIERTA
            caja.save()

            registrar_bitacora_simple(
                usuario=request.user,
                accion="Apertura de caja",
                entidad_id=caja.pk,
                detalles={
                    "monto_inicial": str(caja.monto_inicial),
                    "negocio_id": str(negocio.pk),
                },
            )

            messages.success(request, "Caja abierta correctamente.")
            return redirect("ventas:venta_lista")
    else:
        form = AperturaCajaForm()

    return render(request, "ventas/caja_apertura.html", {"form": form})


@login_required
def caja_arqueo_parcial_view(request):
    negocio = request.user.perfilusuario.negocio

    caja = CajaTurno.objects.filter(
        negocio=negocio,
        estado=CajaTurno.EST_ABIERTA,
    ).first()

    if not caja:
        messages.error(request, "No hay una caja abierta para realizar el arqueo parcial.")
        return redirect("ventas:caja_historial")

    monto_esperado = caja.monto_esperado_efectivo()

    if request.method == "POST":
        form = ArqueoParcialForm(request.POST)
        if form.is_valid():
            arqueo: ArqueoParcial = form.save(commit=False)

            # usar el nombre correcto del campo FK
            arqueo.caja = caja
            arqueo.negocio = negocio  # si agregas este campo más adelante
            arqueo.usuario = request.user
            arqueo.monto_esperado = monto_esperado
            arqueo.diferencia = arqueo.monto_contado - monto_esperado

            arqueo.save()

            messages.success(
                request,
                f"Arqueo parcial registrado correctamente. Diferencia: ${arqueo.diferencia:.0f}",
            )
            return redirect("ventas:caja_historial")
        else:
            messages.error(
                request,
                "No se pudo registrar el arqueo. Revisa los campos del formulario."
            )
            print("ERRORES ARQUEO PARCIAL:", form.errors)
    else:
        form = ArqueoParcialForm()

    return render(
        request,
        "ventas/caja_arqueo_parcial.html",
        {
            "caja": caja,
            "form": form,
            "monto_esperado": monto_esperado,
        },
    )



@login_required
def caja_cierre_view(request):
    negocio = request.user.perfilusuario.negocio
    caja = _caja_abierta(negocio)

    if not caja:
        messages.error(request, "No hay una caja abierta para cerrar.")
        return redirect("ventas:venta_lista")

    monto_esperado = caja.monto_esperado_efectivo()

    if request.method == "POST":
        form = CierreCajaForm(request.POST, instance=caja)
        if form.is_valid():
            caja = form.save(commit=False)
            caja.usuario_cierre = request.user
            caja.fecha_cierre = timezone.now()
            caja.estado = CajaTurno.EST_CERRADA
            caja.save()

            registrar_bitacora_simple(
                usuario=request.user,
                accion="Cierre de caja",
                entidad_id=caja.pk,
                detalles={
                    "monto_inicial": str(caja.monto_inicial),
                    "monto_esperado": str(monto_esperado),
                    "monto_contado": str(caja.monto_contado_cierre),
                    "diferencia": str(
                        (caja.monto_contado_cierre or 0) - monto_esperado
                    ),
                },
            )

            messages.success(request, "Caja cerrada correctamente.")
            return redirect("ventas:venta_lista")
    else:
        form = CierreCajaForm(instance=caja)

    context = {
        "form": form,
        "caja": caja,
        "monto_esperado": monto_esperado,
    }
    return render(request, "ventas/caja_cierre.html", context)


class CajaTurnoListaView(LoginRequiredMixin, ListView):
    """
    Muestra el historial de cajas (turnos) del negocio del usuario.
    """
    model = CajaTurno
    template_name = "ventas/caja_historial.html"
    context_object_name = "cajas"

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return (
            CajaTurno.objects
            .filter(negocio=negocio)
            .select_related("usuario_apertura", "usuario_cierre")
            .prefetch_related("arqueos")
            .order_by("-fecha_apertura")
        )


class CajaTurnoDetalleView(LoginRequiredMixin, DetailView):
    """
    Informe completo de un turno de caja:
    - datos generales
    - ventas por método de pago
    - descuentos
    - anulaciones
    - arqueos parciales
    """
    model = CajaTurno
    template_name = "ventas/caja_detalle.html"
    context_object_name = "caja"

    def get_queryset(self):
        # Seguridad: solo cajas del negocio del usuario
        negocio = self.request.user.perfilusuario.negocio
        return (
            CajaTurno.objects
            .filter(negocio=negocio)
            .select_related("usuario_apertura", "usuario_cierre")
            .prefetch_related("arqueos")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        caja: CajaTurno = self.object

        # 1) Ventas del turno (ya excluye anuladas en el helper)
        ventas_qs = caja.ventas_del_turno().select_related("usuario")

        # 2) Ventas por medio de pago
        totales_medios = caja.ventas_por_medio_pago()

        # 3) Total de ventas del turno
        total_ventas = caja.total_ventas()

        # 4) Total de descuentos aplicados
        items_qs = VentaItem.objects.filter(venta__in=ventas_qs)

        descuento_expr = ExpressionWrapper(
            F("precio_unit") * F("cantidad") * F("descuento_pct") / 100,
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )

        total_descuentos = items_qs.aggregate(
            total=Sum(descuento_expr)
        )["total"] or 0

        # 5) Anulaciones del turno
        anulaciones_qs = Anulacion.objects.filter(
            venta__in=ventas_qs
        ).select_related("venta", "usuario")

        # 6) Monto esperado en caja (efectivo)
        monto_esperado_efectivo = caja.monto_esperado_efectivo()

        # 7) Diferencia final (si está cerrada)
        diferencia_cierre = caja.diferencia_cierre

        context.update(
            {
                "ventas": ventas_qs,
                "totales_medios": totales_medios,
                "total_ventas": total_ventas,
                "total_descuentos": total_descuentos,
                "anulaciones": anulaciones_qs,
                "monto_esperado_efectivo": monto_esperado_efectivo,
                "diferencia_cierre": diferencia_cierre,
            }
        )

        # NOTA: Entradas/salidas de caja extras, ventas en espera cobradas, etc.,
        # las puedes sumar aquí cuando tengas esos modelos / flags.
        return context
    

@login_required
def caja_pdf_view(request, pk):
    """
    Genera un PDF formal del turno de caja usando xhtml2pdf.
    Pensado para funcionar tanto en local como en PythonAnywhere.
    """
    negocio = request.user.perfilusuario.negocio
    caja = get_object_or_404(CajaTurno, pk=pk, negocio=negocio)

    # --- MISMA LÓGICA DE RESUMEN QUE EL DETALLE ---

    # Ventas del turno (ya deberías tener este helper en el modelo)
    ventas_qs = caja.ventas_del_turno().select_related("usuario")

    # Totales por medio de pago
    totales_medios = caja.ventas_por_medio_pago()

    # Total de ventas
    total_ventas = caja.total_ventas()

    # Total de descuentos (sumando descuentos de cada ítem)
    items_qs = VentaItem.objects.filter(venta__in=ventas_qs)
    descuento_expr = ExpressionWrapper(
        F("precio_unit") * F("cantidad") * F("descuento_pct") / 100,
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )
    total_descuentos = items_qs.aggregate(
        total=Sum(descuento_expr)
    )["total"] or 0

    # Anulaciones del turno
    anulaciones_qs = Anulacion.objects.filter(
        venta__in=ventas_qs
    ).select_related("venta", "usuario")

    # Monto esperado en caja y diferencia final
    monto_esperado_efectivo = caja.monto_esperado_efectivo()
    diferencia_cierre = caja.diferencia_cierre

    cajero = caja.usuario_cierre or caja.usuario_apertura

    if cajero:
        cajero_nombre = cajero.get_full_name() or cajero.username
    else:
        cajero_nombre = "____________________________"

    # Buscar algún ADMIN del mismo negocio como supervisor
    supervisor_pu = (
        PerfilUsuario.objects
        .filter(negocio=caja.negocio, rol=PerfilUsuario.ROL_ADMIN)
        .select_related("user")
        .first()
    )
    if supervisor_pu and supervisor_pu.user:
        supervisor_nombre = supervisor_pu.user.get_full_name() or supervisor_pu.user.username
    else:
        supervisor_nombre = "____________________________"


    context = {
        "caja": caja,
        "ventas": ventas_qs,
        "totales_medios": totales_medios,
        "total_ventas": total_ventas,
        "total_descuentos": total_descuentos,
        "anulaciones": anulaciones_qs,
        "monto_esperado_efectivo": monto_esperado_efectivo,
        "diferencia_cierre": diferencia_cierre,
        "cajero_nombre": cajero_nombre,
        "supervisor_nombre": supervisor_nombre,
    }

    # Renderizamos un template especial para PDF (sin Tailwind)
    html_string = render_to_string("ventas/caja_pdf.html", context)

    # Preparamos respuesta HTTP como PDF
    response = HttpResponse(content_type="application/pdf")
    filename = f"caja_{caja.id}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    # Generamos el PDF con xhtml2pdf
    pisa_status = pisa.CreatePDF(
        src=html_string,
        dest=response,
        encoding="UTF-8",
    )

    if pisa_status.err:
        # Puedes logear el error si quieres, pero para título con esto basta
        return HttpResponse("Error al generar el PDF de caja.", status=500)

    return response

