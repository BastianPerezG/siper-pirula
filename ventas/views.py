# ventas/views.py

import json
from django.core.serializers.json import DjangoJSONEncoder
from django.shortcuts import render, redirect, get_list_or_404
from django.views.generic import ListView, DetailView
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Venta,VentaItem,Anulacion
from .forms import VentaForm, VentaItemFormSet
from inventario.models import Producto, MovimientoInventario
from django.db import transaction   
from core.utlis import registrar_bitacora_simple
from core.models import Negocio

import json # Necesario para json.dumps en el contexto
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
            comentario_usuario = form.cleaned_data.get('comentario', '').strip()
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
                    # 'venta.total' ejecuta la suma de los subtotales de los ítems
                    venta.monto_total = venta.total 
                    
                    # Esto congela el total en la base de datos (Inmutabilidad histórica)
                    venta.save(update_fields=['monto_total'])
                    detalles_registro = {
                        'items_vendidos': items_validos,
                        'monto_total': str(venta.monto_total), 
                    }
                    if comentario_usuario:
                        detalles_registro['comentario_usuario'] = comentario_usuario
                    registrar_bitacora_simple(
                        usuario=request.user,
                        accion=f"Creación de Venta POS #{venta.pk}",
                        entidad_id=venta.pk,
                        detalles=detalles_registro
                    )
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
            return render(request, 'ventas/anular_confirmacion.html', {'venta': venta})
            
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

    return render(request, 'ventas/anular_confirmacion.html', {'venta': venta})