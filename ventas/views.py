# ventas/views.py

from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from django.views.decorators.csrf import csrf_exempt

from core.mixins import RolRequeridoMixin, rol_requerido
from .models import PagoVenta, Venta,VentaItem,Anulacion, CajaTurno, ArqueoParcial, DescuentoReglaRol, CodigoAutorizacionDescuento, AuditoriaDescuento
from .forms import AuditoriaDescuentoFiltroForm, CodigoAutorizacionDescuentoForm, DescuentoReglaRolForm, VentaCheckoutForm, VentaForm, VentaItemFormSet, AperturaCajaForm, ArqueoParcialForm, CierreCajaForm, VentaFiltroForm
from inventario.models import Producto, MovimientoInventario
from django.db import transaction   

from core.models import Negocio, PerfilUsuario
from django.db.models import Sum, F, DecimalField, ExpressionWrapper
from .utils import validar_y_auditar_descuento_ticket

# Imports para el PDF
from django.template.loader import render_to_string
from django.http import HttpResponse
from xhtml2pdf import pisa
from core.utils import registrar_bitacora_estructurada
from core.models import Negocio

import json # Necesario para json.dumps en el contexto

def _caja_abierta(negocio):
    """
    Devuelve la caja abierta del negocio o None.
    """
    return CajaTurno.objects.filter(
        negocio=negocio,
        estado=CajaTurno.EST_ABIERTA,
    ).first()


class VentaListaView(RolRequeridoMixin, ListView):
    roles_requeridos = ["CAJERO", "ADMIN"]
    model = Venta
    template_name = "ventas/venta_lista.html"
    context_object_name = "ventas"
    paginate_by = 25

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        qs = Venta.objects.filter(negocio=negocio)
        
        # Aplicar filtros del formulario
        form = VentaFiltroForm(self.request.GET)
        if form.is_valid():
            # Búsqueda por texto (ID o número de documento)
            q = form.cleaned_data.get("q", "").strip()
            if q:
                # Buscar por ID o número de documento
                try:
                    # Intentar buscar por ID
                    venta_id = int(q)
                    qs = qs.filter(id=venta_id)
                except ValueError:
                    # Si no es un número, buscar por número de documento
                    qs = qs.filter(doc_num__icontains=q)
            
            # Filtro por estado
            estado = form.cleaned_data.get("estado")
            if estado:
                qs = qs.filter(estado=estado)
            
            # Filtro por método de pago
            metodo_pago = form.cleaned_data.get("metodo_pago")
            if metodo_pago:
                qs = qs.filter(medio_pago=metodo_pago)
            
            # Filtro por tipo de documento
            doc_tipo = form.cleaned_data.get("doc_tipo")
            if doc_tipo:
                qs = qs.filter(doc_tipo=doc_tipo)
            
            # Filtro por rango de fechas
            fecha_desde = form.cleaned_data.get("fecha_desde")
            fecha_hasta = form.cleaned_data.get("fecha_hasta")
            if fecha_desde:
                qs = qs.filter(fecha__date__gte=fecha_desde)
            if fecha_hasta:
                qs = qs.filter(fecha__date__lte=fecha_hasta)
        
        return qs.order_by("-fecha")
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Agregar el formulario de filtros al contexto
        context["filtro_form"] = VentaFiltroForm(self.request.GET)
        return context


class VentaDetalleView(RolRequeridoMixin, DetailView):
    roles_requeridos = ["CAJERO", "ADMIN"]
    model = Venta
    template_name = "ventas/venta_detalle.html"
    context_object_name = "venta"

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Venta.objects.filter(negocio=negocio)


@login_required
@rol_requerido("MESON", "CAJERO", "ADMIN")
def venta_crear_view(request):
    """
    Crear una venta con ítems (POS simple con escáner EAN).

    Flujo:
      - "Cobrar y cerrar"  -> se crean la Venta y los ítems, y se redirige a checkout
                             para registrar descuento de ticket + pago.
      - "Enviar a espera"  -> la Venta queda ABIERTA (reservas de stock) y se envía
                             a la lista de ventas en espera.
    """
    negocio = request.user.perfilusuario.negocio

    caja = _caja_abierta(negocio)
    if not caja:
        messages.error(
            request,
            "No puedes registrar ventas porque no hay una caja abierta. "
            "Abre caja primero."
        )
        return redirect("ventas:caja_apertura")

    productos = Producto.objects.filter(
        negocio=negocio,
        activo=True
    ).order_by("nombre")

    precios = {str(p.id): int(p.precio) for p in productos}
    productos_ean = {
        p.ean: {"id": p.id, "precio": int(p.precio)}
        for p in productos if p.ean
    }

    if request.method == "POST":
        form = VentaForm(request.POST)
        formset = VentaItemFormSet(
            request.POST,
            form_kwargs={"negocio": negocio, "usuario": request.user}
        )
        accion = request.POST.get("accion", "cerrar")  # "cerrar" o "espera"

        if form.is_valid() and formset.is_valid():
            comentario_usuario = (form.cleaned_data.get("comentario") or "").strip()

            with transaction.atomic():
                venta = form.save(commit=False)
                venta.negocio = negocio

                # IMPORTANTE: Todas las ventas nuevas se crean como ABIERTA
                # - "Enviar a espera" => ABIERTA (genera reservas, queda en espera)
                # - "Cobrar y cerrar" => ABIERTA (genera reservas, luego va al checkout)
                # El checkout es quien cierra la venta después de aplicar descuentos y registrar pagos
                venta.estado = Venta.EST_ABIERTA
                
                # Generar número de documento automáticamente
                venta.doc_num = venta.generar_numero_documento()
                
                venta.save()

                items_validos = 0

                if form.is_valid() and formset.is_valid():
                    comentario_usuario = (form.cleaned_data.get("comentario") or "").strip()
            
                    # 🚨 MODIFICACIÓN: Lista para almacenar los detalles de los ítems para la Bitácora
                    items_para_bitacora = [] 

                    with transaction.atomic():
                        venta = form.save(commit=False)
                        venta.negocio = negocio

                        venta.estado = Venta.EST_ABIERTA
                        venta.doc_num = venta.generar_numero_documento()
                        
                        venta.save()

                        items_validos = 0

                        for item_form in formset:
                            if not item_form.cleaned_data:
                                continue

                            if item_form.cleaned_data.get("DELETE"):
                                continue

                            item = item_form.save(commit=False)

                            if not item.producto_id or not item.cantidad or item.cantidad <= 0:
                                continue

                            item.venta = venta
                            item.precio_unit = item.producto.precio
                            item.save()
                            items_validos += 1
                            
                            # 🚨 MODIFICACIÓN: Capturar detalles del ítem guardado
                            items_para_bitacora.append({
                                'producto_id': item.producto.pk,
                                'nombre': item.producto.nombre,
                                'cantidad': float(item.cantidad), # Usar float() para precisión
                                'precio_unitario': str(item.precio_unit),
                                'subtotal': str(item.subtotal),
                            })
                            # FIN MODIFICACIÓN 🚨

                        if items_validos == 0:
                            transaction.set_rollback(True)
                            form.add_error(
                                None,
                                "La venta debe tener al menos un producto válido."
                            )
                        else:

                            venta.monto_total = venta.total 
                            venta.save(update_fields=['monto_total','estado'])
                            
                            # 🚨 MODIFICACIÓN: Incluir la lista de ítems en los detalles
                            detalles_registro = {
                                'items_vendidos_count': items_validos, # Renombré para evitar conflicto con la lista
                                'monto_total': str(venta.monto_total), 
                                'id_venta': venta.pk,
                                'productos_vendidos': items_para_bitacora, # <-- ¡ESTO ES LO NUEVO!
                            }
                            if comentario_usuario:
                                detalles_registro['comentario_usuario'] = comentario_usuario
                                
                            registrar_bitacora_estructurada(
                                negocio=negocio,
                                usuario=request.user,
                                nombre_modelo='Venta',
                                tipo_accion='CREACION_VENTA', 
                                accion=f"POS #{venta.pk}",
                                entidad_id=venta.pk,
                                detalles=detalles_registro,
                            )
        
                            # ... (redirecciones omitidas) ...
                            if accion == "espera":
                                messages.success(
                                    request,
                                    f"Venta #{venta.pk} enviada a espera correctamente."
                                )
                                return redirect("ventas:ventas_en_espera_lista")
                            else:
                                messages.success(
                                    request,
                                    f"Venta #{venta.pk} creada. Continúa con el cobro."
                                )
                                return redirect("ventas:venta_checkout", pk=venta.pk)

    else:
        # ... (código GET omitido) ...
        form = VentaForm()
        formset = VentaItemFormSet(
            form_kwargs={"negocio": negocio, "usuario": request.user}
        )

    context = {
        "form": form,
        "formset": formset,
        "precios_json": json.dumps(precios),
        "productos_ean_json": json.dumps(productos_ean),
    }
    return render(request, "ventas/venta_form.html", context)





@login_required
@rol_requerido("CAJERO", "ADMIN")
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
                
                # IMPORTANTE: Todas las ventas editadas se mantienen como ABIERTA
                # - "Guardar y dejar en espera" => ABIERTA (queda en espera)
                # - "Guardar y cerrar" => ABIERTA (luego va al checkout)
                # El checkout es quien cierra la venta después de aplicar descuentos y registrar pagos
                venta.estado = Venta.EST_ABIERTA
                
                # Generar número de documento si no existe
                if not venta.doc_num:
                    venta.doc_num = venta.generar_numero_documento()
                
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

                    producto = item_form.cleaned_data.get("producto")

                    if not producto or not item.cantidad or item.cantidad <= 0:
                        continue

                    item.producto = producto
                    item.venta = venta
                    item.precio_unit = producto.precio
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

                    #registrar_bitacora_estructurada(
                       # usuario=request.user,
                        #accion=f"Edición de Venta #{venta.pk}",
                        #entidad_id=venta.pk,
                        #detalles=detalles_registro,
                    #)

                    if accion == "espera":
                        messages.success(
                            request,
                            f"Venta #{venta.pk} actualizada y mantenida en espera.",
                        )
                        return redirect("ventas:ventas_en_espera_lista")
                    else:
                        # "Guardar y cerrar" → redirigir al checkout para aplicar descuentos y registrar pago
                        messages.success(
                            request,
                            f"Venta #{venta.pk} actualizada. Continúa con el cobro.",
                        )
                        return redirect("ventas:venta_checkout", pk=venta.pk)

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

@login_required
@rol_requerido("CAJERO", "ADMIN")
def venta_checkout_view(request, pk):
    """
    Registrar descuento de ticket y pago de una venta.

    Se puede llamar para:
      - Ventas recién creadas por POS (estado ABIERTA, sin pago asociado).
      - Ventas en espera (estado ABIERTA, con reservas de stock).

    IMPORTANTE: Esta vista es la responsable de:
      - Aplicar descuentos de ticket
      - Registrar el/los pago(s)
      - Cerrar la venta (cambiar estado a CERRADA)
      - Convertir reservas en salidas de stock

    Si la venta ya tiene un pago registrado, se redirige al detalle.
    """
    negocio = request.user.perfilusuario.negocio
    venta = get_object_or_404(
        Venta.objects.select_related("negocio"),
        pk=pk,
        negocio=negocio,
    )

    # No permitir checkout sobre ventas anuladas
    if venta.estado == Venta.EST_ANULADA:
        messages.error(request, "No es posible cobrar una venta anulada.")
        return redirect("ventas:venta_detalle", pk=venta.pk)

    # Si ya hay un pago registrado, no volver a cobrar
    if venta.pagos.exists():
        messages.info(request, "Esta venta ya tiene un pago registrado.")
        return redirect("ventas:venta_detalle", pk=venta.pk)

    total_bruto = venta.total

    if request.method == "POST":
        form = VentaCheckoutForm(
            request.POST,
            user=request.user,
            total_bruto=total_bruto,
        )

        if form.is_valid():
            tipo_desc = form.cleaned_data.get("tipo_descuento")
            pct = form.cleaned_data.get("descuento_pct")
            monto_desc = form.cleaned_data.get("descuento_monto") or 0
            motivo = (form.cleaned_data.get("motivo_descuento") or "").strip()
            codigo = (form.cleaned_data.get("codigo_autorizacion") or "").strip()

            # Normalizar: siempre tener un monto de descuento
            if tipo_desc == VentaCheckoutForm.TIPO_PORCENTAJE and pct:
                # Convertir pct a float para el cálculo
                pct_float = float(pct)
                if pct_float > 0:
                    monto_desc = int(round(total_bruto * (pct_float / 100)))
            elif tipo_desc == VentaCheckoutForm.TIPO_MONTO:
                monto_desc = int(monto_desc or 0)
            else:
                # TIPO_NINGUNO
                monto_desc = 0

            total_neto = max(int(total_bruto) - monto_desc, 0)

            with transaction.atomic():
                # Validar reglas de descuento y registrar auditoría ANTES de cerrar
                ok, msg_error = validar_y_auditar_descuento_ticket(
                    user=request.user,
                    venta=venta,
                    total_bruto=total_bruto,
                    pct_descuento=pct if tipo_desc == VentaCheckoutForm.TIPO_PORCENTAJE else None,
                    monto_descuento=monto_desc,
                    motivo=motivo,
                    codigo_ingresado=codigo,
                    request=request,
                )
                if not ok:
                    transaction.set_rollback(True)
                    form.add_error(None, msg_error)
                else:
                    # Convertir reservas en salidas si la venta estaba ABIERTA
                    # (NO usamos cerrar_y_actualizar_stock() porque sobrescribe monto_total sin descuento)
                    if venta.estado == Venta.EST_ABIERTA:
                        from inventario.models import MovimientoInventario
                        for item in venta.items.all():
                            # Buscar reservas asociadas a este item
                            reservas = MovimientoInventario.objects.filter(
                                venta_item=item,
                                tipo=MovimientoInventario.TIPO_RESERVA,
                            )
                            
                            if reservas.exists():
                                # Convertir reservas a salidas
                                for mov in reservas:
                                    mov.tipo = MovimientoInventario.TIPO_SALIDA
                                    comentario_base = mov.comentario or ""
                                    extra = f" → Venta cobrada #{venta.pk}"
                                    mov.comentario = (comentario_base + extra).strip()
                                    mov.save(update_fields=["tipo", "comentario"])
                            else:
                                # Si no hay reservas, crear salida directa (venta directa sin pedido)
                                MovimientoInventario.objects.create(
                                    producto=item.producto,
                                    tipo=MovimientoInventario.TIPO_SALIDA,
                                    cantidad=item.cantidad,
                                    comentario=f"Venta #{venta.pk}",
                                    venta_item=item,
                                )
                    
                    # Actualizar monto_total CON descuento aplicado y cerrar la venta
                    venta.monto_total = Decimal(str(total_neto))
                    venta.estado = Venta.EST_CERRADA
                    venta.medio_pago = form.cleaned_data["metodo_pago"]
                    venta.save(update_fields=["monto_total", "estado", "medio_pago"])

                    metodo_pago = form.cleaned_data["metodo_pago"]
                    
                    # Para todos los métodos, procesar normalmente
                    # Efectivo: completado inmediatamente
                    # Transferencia: pendiente (mostrar datos bancarios)
                    # Tarjeta: pendiente (confirmar manualmente después de usar máquina Transbank)
                    monto_pagado = form.cleaned_data["monto_pagado"]
                    vuelto = form.cleaned_data.get("vuelto", 0)
                    
                    # Determinar estado del pago
                    if metodo_pago == PagoVenta.MET_EFECTIVO:
                        estado_pago = PagoVenta.ESTADO_COMPLETADO  # Efectivo completado inmediatamente
                    else:
                        # Transferencia y tarjeta quedan pendientes hasta confirmación manual
                        estado_pago = PagoVenta.ESTADO_PENDIENTE
                    
                    pago = PagoVenta.objects.create(
                        venta=venta,
                        metodo=metodo_pago,
                        monto=monto_pagado,
                        estado=estado_pago,
                        vuelto=vuelto,
                        usuario_registra=request.user,
                    )
                    
                    # Campos específicos según método de pago
                    if metodo_pago == PagoVenta.MET_TRANSFERENCIA:
                        pago.codigo_referencia = form.cleaned_data.get("codigo_referencia_transferencia", "").strip()
                        pago.banco = form.cleaned_data.get("banco_transferencia", "").strip()
                        pago.cuenta_origen = form.cleaned_data.get("cuenta_origen_transferencia", "").strip()
                        pago.titular_transferencia = form.cleaned_data.get("titular_transferencia", "").strip()
                        pago.save(update_fields=["codigo_referencia", "banco", "cuenta_origen", "titular_transferencia"])
                    elif metodo_pago in [PagoVenta.MET_DEBITO, PagoVenta.MET_CREDITO]:
                        # Para tarjeta, guardar datos opcionales que el cajero puede ingresar
                        pago.ultimos_digitos = form.cleaned_data.get("ultimos_digitos_tarjeta", "").strip()
                        pago.referencia_transaccion = form.cleaned_data.get("referencia_transaccion", "").strip()
                        pago.save(update_fields=["ultimos_digitos", "referencia_transaccion"])
                    
                    # Observaciones si existen
                    observaciones = form.cleaned_data.get("observaciones_pago", "").strip()
                    if observaciones:
                        pago.observaciones = observaciones
                        pago.save(update_fields=["observaciones"])

                    detalles_pago = {
                        "total_bruto": str(total_bruto),
                        "total_neto": str(total_neto),
                        "medio_pago": venta.get_medio_pago_display(),
                        "monto_pagado": str(monto_pagado),
                        "vuelto": str(vuelto),
                        "estado_pago": pago.get_estado_display()
                    }

                    # Agregar detalles de descuento si aplica
                    if monto_desc > 0:
                        detalles_pago.update({
                            "descuento_aplicado": True,
                            "descuento_monto": str(monto_desc),
                            "descuento_motivo": motivo,
                            "descuento_codigo_autorizacion": codigo if codigo else "No requerido"
                        })

                    registrar_bitacora_estructurada(
                        negocio=negocio,
                        usuario=request.user,
                        nombre_modelo='Venta',
                        tipo_accion='COBRO_VENTA',
                        accion=f"Cobro / checkout venta #{venta.pk}",
                        entidad_id=venta.pk,
                        detalles=detalles_pago,
                    )

                    # Redirigir según método de pago
                    if metodo_pago == PagoVenta.MET_EFECTIVO:
                        messages.success(request, f"Venta #{venta.pk} cobrada correctamente.")
                        return redirect("ventas:venta_detalle", pk=venta.pk)
                    elif metodo_pago == PagoVenta.MET_TRANSFERENCIA:
                        # Redirigir a página con datos bancarios y QR
                        messages.info(request, "Venta registrada. Muestra los datos bancarios al cliente.")
                        return redirect("ventas:venta_datos_bancarios", pk=venta.pk)
                    else:  # Tarjeta
                        # Redirigir a detalle para que el cajero confirme después de usar máquina Transbank
                        messages.info(
                            request,
                            "Venta registrada. Procesa el pago con la máquina Transbank y luego confirma el pago."
                        )
                        return redirect("ventas:venta_detalle", pk=venta.pk)

    else:
        initial = {
            "total_bruto": total_bruto,
            "metodo_pago": venta.medio_pago or PagoVenta.MET_EFECTIVO,
            "monto_pagado": total_bruto,
        }
        form = VentaCheckoutForm(
            initial=initial,
            user=request.user,
            total_bruto=total_bruto,
        )

    context = {
        "venta": venta,
        "form": form,
    }
    return render(request, "ventas/venta_checkout.html", context)


class VentaEnEsperaListaView(RolRequeridoMixin, ListView):
    roles_requeridos = ["CAJERO", "ADMIN"]
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
        qs = Venta.objects.filter(negocio=negocio, estado=Venta.EST_ABIERTA)
        
        # Aplicar búsqueda simple
        q = self.request.GET.get("q", "").strip()
        if q:
            try:
                venta_id = int(q)
                qs = qs.filter(id=venta_id)
            except ValueError:
                qs = qs.filter(doc_num__icontains=q)
        
        return qs.order_by("fecha")
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "")
        return context

@login_required
@rol_requerido("CAJERO", "ADMIN")
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

            registrar_bitacora_estructurada(
                negocio=negocio,
                usuario=request.user,
                nombre_modelo='Venta',
                tipo_accion='FINALIZACION_COBRO',
                accion=f"Cobro y cierre de Venta en espera",
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
@rol_requerido("CAJERO", "ADMIN")
def venta_anular_view(request, pk):
    venta = get_object_or_404(Venta, pk=pk, negocio=request.user.perfilusuario.negocio)
    negocio = request.user.perfilusuario.negocio
    
    # Prevenir doble anulación
    if venta.estado == Venta.EST_ANULADA:
        messages.error(request, "Esta venta ya fue anulada.")
        return redirect('ventas:venta_detalle', pk=pk)

    if request.method == 'POST':
        motivo = request.POST.get('motivo')
        
        if not motivo:
            messages.error(request, "Debe especificar un motivo para la anulación.")
            return render(request, 'ventas/venta_anular_confirmacion.html', {'venta': venta})
            
        # 🚨 Inicializar la lista para capturar los ítems anulados
        items_anulados = []

        with transaction.atomic():
            
            # 1. Crear el registro de Anulacion
            anulacion = Anulacion.objects.create(
                venta=venta,
                motivo=motivo,
                usuario=request.user,
                venta_item=None 
            )

            # 2. Revertir el stock y recopilar detalles de los ítems
            for item in venta.items.all():
                
                # Crear un movimiento de ENTRADA para devolver el stock
                MovimientoInventario.objects.create(
                    producto=item.producto,
                    tipo=MovimientoInventario.TIPO_ENTRADA,
                    cantidad=item.cantidad,
                    comentario=f"Reversa por Anulación Total Venta #{venta.pk} (Motivo: {motivo})",
                )
                
                # 🚨 CAPTURAR DETALLES DEL ÍTEM PARA LA BITÁCORA
                items_anulados.append({
                    'producto_id': item.producto.pk,
                    'nombre': item.producto.nombre,
                    'cantidad_revertida': float(item.cantidad),
                    'precio_unitario': str(item.precio_unit),
                    'subtotal_original': str(item.subtotal),
                })
                # FIN CAPTURA 🚨

            # 3. Actualizar el estado de la Venta
            venta.estado = Venta.EST_ANULADA
            venta.save(update_fields=['estado'])
            
            # 4. Registrar la Bitácora
            detalles_registro = {
                'motivo_anulacion': motivo,
                'monto_original': str(venta.monto_total),
                'items_revertidos_count': len(items_anulados), # Usamos la longitud de la lista
                'usuario_anulador_id': str(request.user.pk),
                'productos_anulados': items_anulados, # <-- ¡NUEVA CLAVE CON DETALLES!
            }
            
            registrar_bitacora_estructurada(
                negocio=negocio,
                usuario=request.user,
                nombre_modelo='Venta',
                tipo_accion='ANULACION_VENTA',
                accion=f"Anulación completa de Venta POS #{venta.pk}",
                entidad_id=venta.pk,
                detalles=detalles_registro
            )

            messages.success(request, f"Venta #{venta.pk} anulada y stock revertido correctamente.")
            return redirect('ventas:venta_detalle', pk=pk)

    return render(request, 'ventas/venta_anular_confirmacion.html', {'venta': venta})

@login_required
@rol_requerido("CAJERO", "ADMIN")
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

            
            registrar_bitacora_estructurada(
                negocio=negocio,
                usuario=request.user,
                nombre_modelo="Caja",
                tipo_accion="CAJA_ABIERTA",
                accion=f"Apertura de caja: {caja.pk} por el usuario: {request.user} (id:{request.user.pk})",
                entidad_id=caja.pk,
                detalles={
                'caja_afectada_id': caja.pk,
                'caja_estado': caja.estado,
                'caja_negocio': str(caja.negocio), 
                'usuario_responsable_id': str(request.user.pk),
                'valor_inicial':str(caja.monto_inicial),
            }
            )


            messages.success(request, "Caja abierta correctamente.")
            return redirect("ventas:venta_lista")
    else:
        form = AperturaCajaForm()

    return render(request, "ventas/caja_apertura.html", {"form": form})


@login_required
@rol_requerido("CAJERO", "ADMIN")
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
            detalles_registro={
                'usuario_id':request.user.pk,
                'caja_afectada_id': caja.pk,
                'caja_estado': caja.estado,
                'caja_negocio': str(caja.negocio), 
                'usuario_responsable_id': str(request.user.pk),
                'monto_esperado':str(arqueo.monto_esperado),
                'diferencia':str(arqueo.diferencia),
            }
            registrar_bitacora_estructurada(
                negocio=negocio,
                usuario=request.user,
                nombre_modelo="Caja",
                tipo_accion="CAJA_ARQUEO",
                entidad_id=request.user.pk,
                accion=f"Cierre de sesión exitoso por el usuario {request.user.username} con ID: {request.user.pk}.",
                detalles=detalles_registro
            )
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
@rol_requerido("CAJERO", "ADMIN")
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

            registrar_bitacora_estructurada(
                negocio=negocio,
                usuario=request.user,
                nombre_modelo="Caja",
                tipo_accion="CAJA_CERRADA",
                accion=f"Cierre de caja: {caja.pk} por el usuario: {request.user}",
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


class CajaTurnoListaView(RolRequeridoMixin, ListView):
    roles_requeridos = ["CAJERO", "ADMIN"]
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


class CajaTurnoDetalleView(RolRequeridoMixin, DetailView):
    roles_requeridos = ["CAJERO", "ADMIN"]
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
@rol_requerido("CAJERO", "ADMIN")
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


class DescuentoReglaRolListaView(RolRequeridoMixin, ListView):
    """
    Lista de reglas de descuento por rol.
    """
    required_rol = "ADMIN"
    model = DescuentoReglaRol
    template_name = "ventas/descuento_reglas_lista.html"
    context_object_name = "reglas"
    ordering = ["rol"]


class DescuentoReglaRolCreateView(RolRequeridoMixin, CreateView):
    """
    Crea una nueva regla de tope de descuento para un rol.
    """
    required_rol = "ADMIN"
    model = DescuentoReglaRol
    form_class = DescuentoReglaRolForm
    template_name = "ventas/descuento_regla_form.html"
    success_url = reverse_lazy("ventas:descuento_reglas")

    def form_valid(self, form):
        messages.success(self.request, "Regla de descuento creada correctamente.")
        return super().form_valid(form)


class DescuentoReglaRolUpdateView(RolRequeridoMixin, UpdateView):
    """
    Edita una regla existente.
    """
    required_rol = "ADMIN"
    model = DescuentoReglaRol
    form_class = DescuentoReglaRolForm
    template_name = "ventas/descuento_regla_form.html"
    success_url = reverse_lazy("ventas:descuento_reglas")

    def form_valid(self, form):
        messages.success(self.request, "Regla de descuento actualizada correctamente.")
        return super().form_valid(form)


class DescuentoReglaRolToggleActivoView(RolRequeridoMixin, View):
    """
    Activa/desactiva una regla con un botón en la lista.
    No requiere plantilla propia; redirige de vuelta a la lista.
    """
    required_rol = "ADMIN"

    def post(self, request, pk):
        regla = get_object_or_404(DescuentoReglaRol, pk=pk)
        regla.activo = not regla.activo
        regla.save(update_fields=["activo"])
        estado = "activada" if regla.activo else "desactivada"
        messages.success(request, f"Regla para rol {regla.get_rol_display()} {estado}.")
        return redirect("ventas:descuento_reglas")


class CodigoAutorizacionListaView(RolRequeridoMixin, ListView):
    """
    Lista de códigos de autorización de descuentos.
    """
    required_rol = "ADMIN"
    model = CodigoAutorizacionDescuento
    template_name = "ventas/codigo_descuento_lista.html"
    context_object_name = "codigos"
    ordering = ["codigo"]


class CodigoAutorizacionCreateView(RolRequeridoMixin, CreateView):
    """
    Crea un nuevo código de autorización.
    """
    required_rol = "ADMIN"
    model = CodigoAutorizacionDescuento
    form_class = CodigoAutorizacionDescuentoForm
    template_name = "ventas/codigo_descuento_form.html"
    success_url = reverse_lazy("ventas:codigo_descuento_lista")

    def form_valid(self, form):
        messages.success(self.request, "Código de autorización creado correctamente.")
        return super().form_valid(form)


class CodigoAutorizacionUpdateView(RolRequeridoMixin, UpdateView):
    """
    Edita un código de autorización existente.
    """
    required_rol = "ADMIN"
    model = CodigoAutorizacionDescuento
    form_class = CodigoAutorizacionDescuentoForm
    template_name = "ventas/codigo_descuento_form.html"
    success_url = reverse_lazy("ventas:codigo_descuento_lista")

    def form_valid(self, form):
        messages.success(self.request, "Código de autorización actualizado correctamente.")
        return super().form_valid(form)



class AuditoriaDescuentoListaView(RolRequeridoMixin, ListView):
    """
    Lista de eventos de auditoría de descuentos.

    - Solo accesible para ADMIN (puedes ajustar el rol si quieres).
    - Filtra por negocio del usuario logueado.
    - Aplica filtros de fecha, cajero, autorizador y nivel.
    """
    required_rol = "ADMIN"
    model = AuditoriaDescuento
    template_name = "ventas/descuento_auditoria_lista.html"
    context_object_name = "auditorias"
    paginate_by = 50

    def get_queryset(self):
        # Partimos del queryset base definido en el modelo (ordenado por fecha_hora desc)
        qs = super().get_queryset().select_related(
            "venta",
            "item__producto",
            "usuario_aplica",
            "usuario_autoriza",
        )

        # Filtramos por negocio del usuario (a través de la venta)
        perfil = getattr(self.request.user, "perfilusuario", None)
        if perfil and perfil.negocio_id:
            qs = qs.filter(venta__negocio=perfil.negocio)

        # Aplicamos filtros del formulario
        self.filtro_form = AuditoriaDescuentoFiltroForm(self.request.GET or None)
        qs = self.filtro_form.filtrar_queryset(qs)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Pasamos el formulario al contexto para que la plantilla pueda renderizarlo
        ctx["filtro_form"] = getattr(self, "filtro_form", AuditoriaDescuentoFiltroForm())
        return ctx


class PagoPendienteListaView(RolRequeridoMixin, ListView):
    roles_requeridos = ["ADMIN"]
    """
    Lista de pagos pendientes de confirmación (transferencias).
    Solo accesible para ADMIN.
    """
    roles_requeridos = ["ADMIN"]
    model = PagoVenta
    template_name = "ventas/pago_pendiente_lista.html"
    context_object_name = "pagos_pendientes"
    paginate_by = 25

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        qs = (
            PagoVenta.objects
            .filter(
                venta__negocio=negocio,
                estado=PagoVenta.ESTADO_PENDIENTE
            )
            .select_related("venta", "usuario_registra")
        )
        
        # Aplicar búsqueda
        q = self.request.GET.get("q", "").strip()
        if q:
            try:
                venta_id = int(q)
                qs = qs.filter(venta_id=venta_id)
            except ValueError:
                # Buscar por número de documento de la venta
                qs = qs.filter(venta__doc_num__icontains=q)
        
        # Filtro por método de pago
        metodo = self.request.GET.get("metodo", "")
        if metodo:
            qs = qs.filter(metodo=metodo)
        
        return qs.order_by("-fecha_hora")
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "")
        context["metodo"] = self.request.GET.get("metodo", "")
        context["metodos_pago"] = PagoVenta.METODOS
        return context


@login_required
@rol_requerido("ADMIN")
def pago_confirmar_view(request, pk):
    """
    Confirma un pago pendiente (transferencia).
    Solo ADMIN puede confirmar.
    """
    # Verificar que sea ADMIN
    perfil = getattr(request.user, "perfilusuario", None)
    if not perfil or perfil.rol != "ADMIN":
        raise PermissionDenied("Solo los administradores pueden confirmar pagos pendientes.")
    
    pago = get_object_or_404(
        PagoVenta.objects.select_related("venta"),
        pk=pk,
        estado=PagoVenta.ESTADO_PENDIENTE
    )
    
    # Verificar que el pago pertenezca al negocio del usuario
    if pago.venta.negocio != request.user.perfilusuario.negocio:
        raise PermissionDenied("No tienes permisos para confirmar este pago.")
    
    if request.method == "POST":
        with transaction.atomic():
            try:
                pago.confirmar(request.user)
                
                registrar_bitacora_estructurada(
                    usuario=request.user,
                    accion=f"Confirmación de pago #{pago.pk} - Venta #{pago.venta.pk}",
                    entidad_id=pago.venta.pk,
                    detalles=(
                        f"Método: {pago.get_metodo_display()} | "
                        f"Monto: ${pago.monto} | "
                        f"Código referencia: {pago.codigo_referencia or 'N/A'}"
                    ),
                )
                
                messages.success(
                    request,
                    f"Pago de ${pago.monto} confirmado correctamente para la venta #{pago.venta.pk}."
                )
                return redirect("ventas:venta_detalle", pk=pago.venta.pk)
            except ValidationError as e:
                messages.error(request, str(e))
                return redirect("ventas:venta_detalle", pk=pago.venta.pk)
    
    # GET: mostrar confirmación
    context = {
        "pago": pago,
        "venta": pago.venta,
    }
    return render(request, "ventas/pago_confirmar.html", context)


@login_required
@rol_requerido("CAJERO", "ADMIN")
def venta_datos_bancarios_view(request, pk):
    """
    Muestra los datos bancarios del negocio para que el cliente realice la transferencia.
    Incluye QR con la información de pago.
    """
    import io
    import base64
    import json
    
    negocio = request.user.perfilusuario.negocio
    venta = get_object_or_404(
        Venta.objects.select_related("negocio"),
        pk=pk,
        negocio=negocio,
    )
    
    # Buscar el pago pendiente de transferencia
    pago = venta.pagos.filter(
        metodo=PagoVenta.MET_TRANSFERENCIA,
        estado=PagoVenta.ESTADO_PENDIENTE
    ).first()
    
    if not pago:
        messages.error(request, "No se encontró un pago pendiente de transferencia para esta venta.")
        return redirect("ventas:venta_detalle", pk=venta.pk)
    
    # Generar código QR con los datos bancarios
    # Nota: Los bancos chilenos no usan un estándar unificado para QR de transferencias.
    # Generamos un QR con texto plano legible que el usuario puede copiar manualmente
    # o que algunas apps pueden leer como información de contacto.
    qr_image_base64 = None
    qr_error = None
    
    if negocio.tiene_datos_bancarios():
        try:
            import qrcode
            
            # Crear el contenido del QR en formato de texto plano legible
            # Formato simple que puede ser leído por humanos y algunas apps
            monto = int(venta.monto_total or venta.total)
            
            # Formato de texto plano con información estructurada
            qr_lines = [
                f"TRANSFERENCIA BANCARIA",
                f"",
                f"Banco: {negocio.banco_nombre or 'N/A'}",
                f"Tipo Cuenta: {negocio.banco_tipo_cuenta or 'N/A'}",
                f"Numero Cuenta: {negocio.banco_numero_cuenta or 'N/A'}",
                f"RUT: {negocio.banco_rut_titular or 'N/A'}",
                f"Titular: {negocio.banco_nombre_titular or 'N/A'}",
                f"",
                f"Monto: ${monto:,}",
                f"Concepto: Venta #{venta.id} - {negocio.nombre}",
            ]
            
            qr_string = "\n".join(qr_lines)
            
            # Generar QR con mayor tamaño para mejor legibilidad
            qr = qrcode.QRCode(
                version=None,  # Auto-detect version
                error_correction=qrcode.constants.ERROR_CORRECT_M,  # Mayor corrección de errores
                box_size=8,
                border=4,
            )
            qr.add_data(qr_string)
            qr.make(fit=True)
            
            # Crear imagen (qrcode usa PIL/Pillow por defecto)
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Convertir a base64 para mostrar en el template
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            qr_image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            
        except ImportError as e:
            # Si no está instalada la librería
            qr_error = f"Librería qrcode no instalada: {e}"
        except Exception as e:
            # Si hay algún error en la generación
            qr_error = f"Error generando QR: {str(e)}"
    
    context = {
        "venta": venta,
        "pago": pago,
        "negocio": negocio,
        "qr_image_base64": qr_image_base64,
        "qr_error": qr_error,
    }
    return render(request, "ventas/venta_datos_bancarios.html", context)


@login_required
@rol_requerido("CAJERO", "ADMIN")
def venta_nota_imprimir_view(request, pk):
    """
    Genera una nota de venta (boleta térmica) con el detalle de la compra.
    """
    negocio = request.user.perfilusuario.negocio
    venta = get_object_or_404(
        Venta.objects.select_related("negocio", "pedido")
        .prefetch_related("items__producto"),
        pk=pk,
        negocio=negocio,
    )
    
    context = {
        "venta": venta,
        "negocio": negocio,
    }
    return render(request, "ventas/venta_nota_imprimir.html", context)