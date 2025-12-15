# inventario/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic import DetailView, CreateView, UpdateView, ListView, DeleteView,View, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.utils.safestring import mark_safe
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q
from core.models import Negocio
from core.utils import registrar_bitacora_estructurada
from core.models import BitacoraAccion
from core.mixins import RolRequeridoMixin, rol_requerido 


from .models import (
    Producto, 
    MovimientoInventario, 
    Compra,Proveedor,
    PlantillaProveedorProducto, 
    Categoria,
    Marca,
    Promo,
    PromoItem,
)

from .forms import (
    ProductoCrearForm, 
    MovimientoCrearForm, 
    CompraItemFormSet, 
    CompraForm,
    PlantillaProveedorProductoForm,
    ProveedorForm,
    PromoForm,
    PromoItemFormSet,
    MermaForm,
)

import json

# --- SCAN EAN ---

@login_required
def scan_ean(request):
    """
    Lee el EAN desde el input, busca el producto y redirige:
    - si existe -> detalle
    - si no existe -> formulario de creación con EAN precargado
    """
    ean = request.GET.get("ean", "").strip()
    negocio = request.user.perfilusuario.negocio

    if ean:
        try:
            producto = Producto.objects.get(ean=ean, negocio=negocio)
            return redirect("inventario:producto_detalle", pk=producto.pk)
        except Producto.DoesNotExist:
            url = reverse("inventario:producto_crear")
            return redirect(f"{url}?ean={ean}")

    return render(request, "inventario/scan.html")

def get_negocio_actual(request):
    # Usa tu propia lógica; aquí un ejemplo simple
    return Negocio.objects.first()

# --- CBVs para productos ---

class ProductoListaView(RolRequeridoMixin, ListView):
    roles_requeridos = ["MESON", "CAJERO", "ADMIN"]
    model = Producto
    template_name = "inventario/productos/producto_lista.html"
    context_object_name = "productos"
    paginate_by = 25

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        qs = Producto.objects.filter(negocio=negocio)

        categoria_id = self.request.GET.get("categoria")
        proveedor_id = self.request.GET.get("proveedor")
        estado = self.request.GET.get("estado", "activos")
        stock_critico = self.request.GET.get("stock_critico")
        q = (self.request.GET.get("q") or "").strip()

        # Estado: activos / inactivos / todos
        if estado == "activos":
            qs = qs.filter(activo=True)
        elif estado == "inactivos":
            qs = qs.filter(activo=False)
        # "todos" -> no filtramos por activo

        if categoria_id:
            qs = qs.filter(categoria_id=categoria_id)

        if proveedor_id:
            qs = qs.filter(proveedor_id=proveedor_id)

        if q:
            qs = qs.filter(
                Q(nombre__icontains=q)
                | Q(ean__icontains=q)
                | Q(sku__icontains=q)
            )

        # Guardar stock_critico flag para filtrar después en get_context_data
        self._stock_critico_filter = stock_critico == "1"

        return qs.order_by("nombre")

    def get_queryset_filtered(self):
        """Aplica el filtro de stock crítico en Python (stock_actual es property)"""
        qs = super().get_queryset()
        if getattr(self, '_stock_critico_filter', False):
            return [p for p in qs if p.stock_actual < p.stock_min]
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        negocio = self.request.user.perfilusuario.negocio

        ctx["categorias"] = Categoria.objects.filter(
            negocio=negocio, activo=True
        ).order_by("nombre")

        ctx["proveedores"] = Proveedor.objects.filter(
            negocio=negocio, activo=True
        ).order_by("nombre")

        # Contador de productos con stock crítico (calculado en Python)
        all_productos = Producto.objects.filter(negocio=negocio, activo=True)
        ctx["productos_criticos_count"] = len([p for p in all_productos if p.stock_actual < p.stock_min])

        # Si está activo el filtro de stock crítico, aplicar en Python
        stock_critico = self.request.GET.get("stock_critico", "")
        if stock_critico == "1":
            # Reemplazar la lista de productos con los filtrados
            productos_filtrados = [p for p in self.object_list if p.stock_actual < p.stock_min]
            ctx["productos"] = productos_filtrados
            ctx["is_paginated"] = False  # Desactivar paginación para este filtro

        categoria_get = self.request.GET.get("categoria")
        proveedor_get = self.request.GET.get("proveedor")

        ctx["filtros"] = {
            "categoria": int(categoria_get) if categoria_get else None,
            "proveedor": int(proveedor_get) if proveedor_get else None,
            "estado": self.request.GET.get("estado", "activos"),
            "stock_critico": stock_critico,
            "q": (self.request.GET.get("q") or "").strip(),
        }
        return ctx



class ProductoDetalleView(RolRequeridoMixin, DetailView):
    roles_requeridos = ["MESON", "CAJERO", "ADMIN"]
    model = Producto
    template_name = "inventario/productos/producto_detalle.html"
    context_object_name = "producto"

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Producto.objects.filter(negocio=negocio)


class ProductoCrearView(RolRequeridoMixin, CreateView):
    roles_requeridos = ["MESON", "CAJERO", "ADMIN"]
    model = Producto
    form_class = ProductoCrearForm
    template_name = "inventario/productos/producto_crear.html"
    success_url = reverse_lazy("inventario:producto_lista")

    def get_initial(self):
        initial = super().get_initial()
        ean = self.request.GET.get("ean", "")
        if ean:
            initial["ean"] = ean
        return initial
    
    def form_valid(self, form):
        producto = form.save(commit=False)
        producto.negocio = self.request.user.perfilusuario.negocio
        producto.save()
        detalles_registro = {
            'id_producto': producto.pk,
            'nombre_producto': producto.nombre,
            'sku': producto.sku, # Asumiendo que tienes un campo SKU
            'ean': producto.ean or 'N/A',
            'precio_inicial': str(producto.precio),
            'usuario_creador_id': str(self.request.user.pk),
        }
        negocio=self.request.user.perfilusuario.negocio
        registrar_bitacora_estructurada(
            negocio=negocio,
            usuario=self.request.user,
            accion=f"Producto creado: {producto.nombre}",
            tipo_accion='CREACION',
            nombre_modelo='Inventario',
            entidad_id=producto.pk,
            detalles=detalles_registro
        )
        messages.success(self.request, f"Producto '{producto.nombre}' creado correctamente.")
        return super().form_valid(form)
    

class ProductoActualizarView(RolRequeridoMixin, UpdateView):
    roles_requeridos = ["MESON", "CAJERO", "ADMIN"]
    model = Producto
    form_class = ProductoCrearForm
    template_name = "inventario/productos/producto_editar.html"
    context_object_name = "producto"

    def get_queryset(self):
        # Seguridad: solo productos del negocio del usuario
        negocio = self.request.user.perfilusuario.negocio
        return Producto.objects.filter(negocio=negocio)

    def form_valid(self, form):
        # 1. Obtener los datos ANTES de guardar (instancia original)
        # El formulario ya contiene una copia de los datos guardados en 'self.object'
        negocio = self.request.user.perfilusuario.negocio        # 2. Registrar los cambios
        
        # form.changed_data contiene una lista de campos que fueron modificados
        if form.changed_data:
            cambios = {}
            # Iteramos sobre todos los campos que Django detectó como modificados
            for field_name in form.changed_data:
                # Obtenemos los valores. 
                # form.initial[field_name] es el valor original (antes de la edición)
                # form.cleaned_data[field_name] es el nuevo valor (después de la edición)
                
                old_value = form.initial.get(field_name, 'N/A')
                new_value = form.cleaned_data.get(field_name, 'N/A')
                
                # Almacenamos el cambio de forma legible
                cambios[field_name] = {
                    'anterior': str(old_value),
                    'nuevo': str(new_value)
                }
            
            # 3. Registrar en la bitácora
            producto = self.object # El objeto antes de guardar
            
            detalles_registro = {
                'id_producto':producto.pk,
                'nombre_producto': producto.nombre,
                'sku': producto.sku,
                'cambios_registrados': cambios, # Incluimos el diccionario de cambios
            }
            
            registrar_bitacora_estructurada(
                negocio=negocio,
                usuario=self.request.user,
                accion=f"Producto actualizado: {producto.nombre}",
                tipo_accion="ACTUALIZACION",  # Tipo de acción: ACTUALIZACION
                nombre_modelo="Inventario",
                entidad_id=producto.pk,
                detalles=detalles_registro
            )

        # 4. Finalizar la operación de actualización
        response = super().form_valid(form) # Esto guarda los nuevos datos
        messages.success(self.request, "Producto actualizado correctamente.")
        return response

    def get_success_url(self):
        # Volver al detalle del producto editado
        return reverse("inventario:producto_detalle", args=[self.object.pk])



@login_required
@rol_requerido("MESON", "CAJERO", "ADMIN")
def producto_toggle_activo(request, pk):
    if request.method != "POST":
        return redirect("inventario:producto_lista")

    producto = get_object_or_404(
        Producto,
        pk=pk,
        negocio=request.user.perfilusuario.negocio,
    )
    
    # El valor antes del cambio
    was_active = producto.activo 
    
    # 1. Cambia el estado y guarda
    producto.activo = not was_active
    producto.save(update_fields=["activo"])

    # 2. Determinar la acción y registrar en Bitácora
    if producto.activo:
        # El producto FUE activado (estaba inactivo, ahora está activo)
        estado_accion = "activado"
        tipo_log = 'ACTIVACION'
        accion_descripcion = f"Producto activado: {producto.nombre}"
    else:
        # El producto FUE desactivado (estaba activo, ahora está inactivo)
        estado_accion = "desactivado"
        tipo_log = 'DESACTIVADO' # Se usa ELIMINACION para borrado lógico
        accion_descripcion = f"Producto desactivado (Borrado Lógico): {producto.nombre}"
        
    # 3. Preparar detalles del registro
    detalles_registro = {
        'nombre_producto': producto.nombre,
        'sku': producto.sku,
        'estado_anterior': 'Activo' if was_active else 'Inactivo',
        'estado_nuevo': 'Activo' if producto.activo else 'Inactivo',
    }

    # 4. Registrar en la bitácora
    registrar_bitacora_estructurada(
        negocio=request.user.perfilusuario.negocio,
        usuario=request.user,
        accion=accion_descripcion,
        tipo_accion=tipo_log,
        nombre_modelo='Inventario',
        entidad_id=producto.pk,
        detalles=detalles_registro
    )
    
    messages.success(request, f"Producto {estado_accion} correctamente.")

    return redirect("inventario:producto_lista")

# --- Movimientos de stock ---
class FlujosInventarioView(RolRequeridoMixin, TemplateView):
    roles_requeridos = ["MESON", "CAJERO", "ADMIN"]
    template_name = "inventario/movimiento_stock/flujos_dashboard.html"


class MovimientoCrearView(RolRequeridoMixin, CreateView):
    roles_requeridos = ["MESON", "CAJERO", "ADMIN"]
    model = MovimientoInventario
    form_class = MovimientoCrearForm
    template_name = "inventario/movimiento_stock/movimiento_crear.html"

    def dispatch(self, request, *args, **kwargs):
        negocio = request.user.perfilusuario.negocio
        self.producto = get_object_or_404(
            Producto,
            pk=kwargs["producto_pk"],
            negocio=negocio,
        )
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.producto = self.producto
        form.instance.usuario = self.request.user
        movimiento = form.save()
        accion_desc = f"Registro de Movimiento de Stock ({movimiento.get_tipo_display()}): {self.producto.nombre}"
        MAPEO_TIPO_LOG = {
            MovimientoInventario.TIPO_ENTRADA: "ENTRADA",
            MovimientoInventario.TIPO_SALIDA: "SALIDA",
            MovimientoInventario.TIPO_AJUSTE: "AJUSTE",
            MovimientoInventario.TIPO_MERMA: "MERMA",
            MovimientoInventario.TIPO_RESERVA: "RESERVA",
            MovimientoInventario.TIPO_VENTA: "VENTA",
        }
        tipo_bd = movimiento.tipo 

        # 2. Usar el mapeo para obtener el nombre del log
        tipo_accion_log = MAPEO_TIPO_LOG.get(tipo_bd, "MOVIMIENTO")
        negocio= self.request.user.perfilusuario.negocio
        detalles_registro = {
            'producto_afectado_id': self.producto.pk,
            'producto_nombre': self.producto.nombre,
            'tipo_movimiento': movimiento.get_tipo_display(), # 'ENTRADA', 'SALIDA', 'AJUSTE', etc.
            'cantidad_movida': str(movimiento.cantidad),
            'comentario_registro': movimiento.comentario or 'N/A',
            'usuario_responsable_id': str(self.request.user.pk),
        }
        
        registrar_bitacora_estructurada(
            negocio=negocio,
            usuario=self.request.user,
            nombre_modelo='Inventario',
            tipo_accion=tipo_accion_log,
            accion=accion_desc,
            entidad_id=movimiento.pk,
            detalles=detalles_registro
        )
        

        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("inventario:producto_detalle", kwargs={"pk": self.producto.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["producto"] = self.producto
        return context


class MovimientoListaView(RolRequeridoMixin, ListView):
    roles_requeridos = ["MESON", "CAJERO", "ADMIN"]
    model = MovimientoInventario
    template_name = "inventario/movimiento_stock/movimiento_lista.html"
    context_object_name = "movimientos"
    paginate_by = 25

    def dispatch(self, request, *args, **kwargs):
        negocio = request.user.perfilusuario.negocio
        self.producto = get_object_or_404(
            Producto,
            pk=kwargs["producto_pk"],
            negocio=negocio,
        )
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return self.producto.movimientos.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["producto"] = self.producto
        return context


class ProductoStockCriticoView(RolRequeridoMixin, ListView):
    roles_requeridos = ["MESON", "CAJERO", "ADMIN"]
    model = Producto
    template_name = "inventario/movimiento_stock/stock_critico.html"
    context_object_name = "productos"

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        qs = Producto.objects.filter(negocio=negocio, activo=True)
        return [p for p in qs if p.stock_actual < p.stock_min]


# --- Compras a proveedores ---

class CompraListaView(RolRequeridoMixin, ListView):
    roles_requeridos = ["CAJERO", "ADMIN"]
    model = Compra
    template_name = "inventario/compras/compra_lista.html"
    context_object_name = "compras"

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        qs = Compra.objects.filter(negocio=negocio)

        proveedor_id = self.request.GET.get("proveedor")
        fecha_desde = self.request.GET.get("desde")
        fecha_hasta = self.request.GET.get("hasta")
        q = (self.request.GET.get("q") or "").strip()

        if proveedor_id:
            qs = qs.filter(proveedor_id=proveedor_id)

        if fecha_desde:
            qs = qs.filter(fecha__date__gte=fecha_desde)

        if fecha_hasta:
            qs = qs.filter(fecha__date__lte=fecha_hasta)

        if q:
            filtro = Q(doc_num__icontains=q) | Q(comentario__icontains=q)
            if q.isdigit():
                filtro |= Q(id=int(q))
            qs = qs.filter(filtro)

        return qs.order_by("-fecha")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        negocio = self.request.user.perfilusuario.negocio

        ctx["proveedores"] = Proveedor.objects.filter(
            negocio=negocio, activo=True
        ).order_by("nombre")

        ctx["filtros"] = {
            "proveedor": self.request.GET.get("proveedor", ""),
            "desde": self.request.GET.get("desde", ""),
            "hasta": self.request.GET.get("hasta", ""),
            "q": (self.request.GET.get("q") or "").strip(),
        }
        return ctx



class CompraDetalleView(RolRequeridoMixin, DetailView):
    roles_requeridos = ["CAJERO", "ADMIN"]
    model = Compra
    template_name = "inventario/compras/compra_detalle.html"
    context_object_name = "compra"

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Compra.objects.filter(negocio=negocio)

@login_required
def compra_crear_view(request):
    negocio = request.user.perfilusuario.negocio

    # Mapa de costos y productos
    productos = Producto.objects.filter(negocio=negocio, activo=True).select_related('proveedor')
    costos_map = {str(p.id): float(p.costo or 0) for p in productos}
    ean_map = {str(p.ean): str(p.id) for p in productos if p.ean}
    
    # Mapa de productos por proveedor (para filtro dinámico)
    productos_por_proveedor = {}
    for p in productos:
        prov_id = str(p.proveedor_id) if p.proveedor_id else "0"
        if prov_id not in productos_por_proveedor:
            productos_por_proveedor[prov_id] = []
        productos_por_proveedor[prov_id].append({
            "id": p.id,
            "nombre": p.nombre,
            "sku": p.sku or "",
            "ean": p.ean or "",
        })
    
    # Mapa de búsqueda extendida (nombre, SKU, EAN -> id)
    busqueda_map = {}
    for p in productos:
        # Agregar EAN
        if p.ean:
            busqueda_map[p.ean.lower()] = str(p.id)
        # Agregar SKU
        if p.sku:
            busqueda_map[p.sku.lower()] = str(p.id)
        # Agregar nombre (primeras palabras)
        busqueda_map[p.nombre.lower()] = str(p.id)

    if request.method == "POST":
        form = CompraForm(request.POST, request.FILES, negocio=negocio)
        formset = CompraItemFormSet(
            request.POST,
            form_kwargs={"negocio": negocio},
        )

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                compra = form.save(commit=False)
                compra.negocio = negocio
                compra.usuario = request.user
                compra.save()

                formset.instance = compra
                formset.save()

            messages.success(request, "Compra registrada correctamente.")
            return redirect("inventario:compra_detalle", pk=compra.pk)
    else:
        form = CompraForm(negocio=negocio)
        formset = CompraItemFormSet(form_kwargs={"negocio": negocio})

    context = {
        "form": form,
        "formset": formset,
        "costos_json": json.dumps(costos_map),
        "ean_map_json": json.dumps(ean_map),
        "productos_por_proveedor_json": json.dumps(productos_por_proveedor),
        "busqueda_map_json": json.dumps(busqueda_map),
    }
    return render(request, "inventario/compras/compra_crear.html", context)


@login_required
@rol_requerido("CAJERO", "ADMIN")
def compra_editar_view(request, pk):
    negocio = request.user.perfilusuario.negocio
    compra = get_object_or_404(Compra, pk=pk, negocio=negocio)

    productos = Producto.objects.filter(negocio=negocio, activo=True)
    costos_map = {str(p.id): p.costo for p in productos}
    ean_map = {str(p.ean): str(p.id) for p in productos}

    if request.method == "POST":
        form = CompraForm(request.POST, request.FILES, instance=compra, negocio=negocio)
        formset = CompraItemFormSet(
            request.POST,
            instance=compra,
            form_kwargs={"negocio": negocio},
        )

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                form.save()
                formset.save()
            messages.success(request, "Compra actualizada correctamente.")
            return redirect("inventario:compra_detalle", pk=compra.pk)
    else:
        form = CompraForm(instance=compra, negocio=negocio)
        formset = CompraItemFormSet(instance=compra, form_kwargs={"negocio": negocio})

    context = {
        "form": form,
        "formset": formset,
        "costos_json": json.dumps(costos_map),
        "ean_map_json": json.dumps(ean_map),
        "modo": "editar",
        "compra": compra,
    }
    return render(request, "inventario/compras/compra_crear.html", context)


class CompraEliminarView(RolRequeridoMixin, DeleteView):
    roles_requeridos = ["CAJERO", "ADMIN"]
    model = Compra
    template_name = "inventario/compras/compra_confirmar_eliminar.html"
    success_url = reverse_lazy("inventario:compra_lista")

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Compra.objects.filter(negocio=negocio)
    

#==================sebastian-proveedores======================#
#=============================================================#
class ProveedorListView(RolRequeridoMixin, ListView):
    roles_requeridos = ["CAJERO", "ADMIN"]
    """Lista de proveedores del negocio, con buscador y filtro por estado."""
    model = Proveedor
    template_name = "inventario/proveedores/proveedor_lista.html"
    context_object_name = "proveedores"
    paginate_by = 25

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio

        qs = Proveedor.objects.filter(negocio=negocio)

        estado = self.request.GET.get("estado", "activos")
        q = (self.request.GET.get("q") or "").strip()

        # filtro por estado
        if estado == "activos":
            qs = qs.filter(activo=True)
        elif estado == "inactivos":
            qs = qs.filter(activo=False)
        # "todos" => no filtramos

        # buscador por nombre / contacto / correo
        if q:
            qs = qs.filter(
                Q(nombre__icontains=q)
                | Q(contacto__icontains=q)
                | Q(correo__icontains=q)
            )

        return qs.order_by("nombre")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filtros"] = {
            "q": (self.request.GET.get("q") or "").strip(),
            "estado": self.request.GET.get("estado", "activos"),
        }
        ctx["url_crear_proveedor"] = reverse_lazy("inventario:proveedor_crear")
        return ctx

# ----------------------------------------------------
# B. CREAR PROVEEDOR (CREATE)
# ----------------------------------------------------
class ProveedorCreateView(RolRequeridoMixin, CreateView):
    roles_requeridos = ["CAJERO", "ADMIN"]
    """Permite crear un nuevo proveedor."""
    model = Proveedor
    form_class = ProveedorForm
    template_name = "inventario/proveedores/proveedor_crear.html" # Template único para crear/editar
    success_url = reverse_lazy("inventario:proveedor_lista") # Redirigir a la lista al éxito

   
    def form_valid(self, form):
        # Asigna automáticamente el negocio del usuario (asumiendo que tu perfil lo tiene)
        form.instance.negocio = self.request.user.perfilusuario.negocio 
        return super().form_valid(form)




# ----------------------------------------------------
# C. ACTUALIZAR PROVEEDOR (UPDATE)
# ----------------------------------------------------
class ProveedorUpdateView(RolRequeridoMixin, UpdateView):
    roles_requeridos = ["CAJERO", "ADMIN"]
    """Permite editar un proveedor existente."""
    model = Proveedor
    form_class = ProveedorForm
    template_name = "inventario/proveedores/proveedor_editar.html"
    context_object_name = 'proveedor'
    success_url = reverse_lazy("inventario:proveedor_lista")

# ----------------------------------------------------
# D. DETALLE DE PROVEEDOR (DETAIL)
# ----------------------------------------------------

class ProveedorDetailView(RolRequeridoMixin, DetailView):
    roles_requeridos = ["CAJERO", "ADMIN"]
    """Muestra el detalle de un proveedor específico y su plantilla asociada."""
    model = Proveedor
    template_name = "inventario/proveedores/proveedor_detalle.html" # Nuevo template
    context_object_name = 'proveedor' # El objeto se pasará al template como 'proveedor'

    # Opcional: Sobrescribir get_queryset para asegurar la seguridad por negocio
    def get_queryset(self):
        # Asegura que solo se puedan ver proveedores que pertenezcan al negocio del usuario
        negocio = self.request.user.perfilusuario.negocio
        return Proveedor.objects.filter(negocio=negocio, activo=True)
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        proveedor = self.object # El proveedor actual

        

        # 2. Obtener TODOS los productos del inventario que utilizan este proveedor.
        # Asumiendo que el modelo Producto tiene un ForeignKey a Proveedor llamado 'proveedor'
        context['productos_del_proveedor'] = Producto.objects.filter(
            proveedor=proveedor,
            negocio=self.request.user.perfilusuario.negocio
        ).order_by('nombre')
        
        return context


class ProveedorToggleActivoView(RolRequeridoMixin, View):
    roles_requeridos = ["CAJERO", "ADMIN"]
    """
    Soft delete: alterna proveedor.activo en lugar de borrar.
    Se llama siempre por POST.
    """
    def post(self, request, pk):
        negocio = request.user.perfilusuario.negocio
        proveedor = get_object_or_404(
            Proveedor,
            pk=pk,
            negocio=negocio,
        )
        proveedor.activo = not proveedor.activo
        proveedor.save(update_fields=["activo"])
        messages.success(
            request,
            f"Proveedor {'activado' if proveedor.activo else 'desactivado'} correctamente."
        )
        return redirect("inventario:proveedor_lista")

#=============sebastian-plantilla de proveedores================#

class PlantillaProveedorProductoListView(LoginRequiredMixin, ListView):
    # Modelo CORREGIDO
    model = PlantillaProveedorProducto 
    template_name = "inventario/proveedores/plantilla_lista.html" # Nuevo template
    context_object_name = "plantillas"

    def get_queryset(self):
        # Filtra por proveedor_id de la URL y por negocio del usuario
        proveedor_id = self.kwargs["proveedor_id"]
        negocio = self.request.user.perfilusuario.negocio
        
        return PlantillaProveedorProducto.objects.filter(
            proveedor_id=proveedor_id,
            proveedor__negocio=negocio, # Filtro de seguridad por negocio
            is_active=True
        ).select_related('producto')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Filtra el proveedor por su negocio para evitar acceso a proveedores de otros negocios
        context["proveedor"] = get_object_or_404(
            Proveedor, 
            id=self.kwargs["proveedor_id"], 
            negocio=self.request.user.perfilusuario.negocio
        )
        return context


class PlantillaProveedorProductoCreateView(LoginRequiredMixin, CreateView): # USANDO MIXIN CORREGIDO
    # Modelo CORREGIDO
    model = PlantillaProveedorProducto 
    form_class = PlantillaProveedorProductoForm # Formulario CORREGIDO
    template_name = "inventario/proveedores/form_proveedores.html" # Nuevo template

    def form_valid(self, form):
        # Asegurar que la plantilla se asocia al proveedor correcto de la URL
        proveedor = get_object_or_404(
            Proveedor, 
            id=self.kwargs["proveedor_id"], 
            negocio=self.request.user.perfilusuario.negocio
        )
        form.instance.proveedor = proveedor
        return super().form_valid(form)

    def get_success_url(self):
        return reverse(
            "inventario:proveedor_lista", # Ajustar URL
            kwargs={"proveedor_id": self.kwargs["proveedor_id"]}
        )


class PlantillaProveedorProductoUpdateView(LoginRequiredMixin, UpdateView): # USANDO MIXIN CORREGIDO
    # Modelo CORREGIDO
    model = PlantillaProveedorProducto
    form_class = PlantillaProveedorProductoForm # Formulario CORREGIDO
    template_name = "inventario/proveedores/form_productos_proveedor.html" # Nuevo template

    def get_queryset(self):
        # Asegurar que solo se pueda editar la plantilla de su negocio
        negocio = self.request.user.perfilusuario.negocio
        return PlantillaProveedorProducto.objects.filter(proveedor__negocio=negocio)

    def get_success_url(self):
        # Redirige a la lista de plantillas del proveedor
        return reverse(
            "inventario:plantilla_lista",
            kwargs={"proveedor_id": self.object.proveedor.id}
        )


class PlantillaProveedorProductoHideView(LoginRequiredMixin, View): # USANDO MIXIN CORREGIDO
    def get(self, request, pk):
        negocio = request.user.perfilusuario.negocio
        
        plantilla = get_object_or_404(
            PlantillaProveedorProducto, 
            pk=pk, 
            proveedor__negocio=negocio # Filtro de seguridad
        )
        plantilla.is_active = False
        plantilla.save()
        
        return redirect("inventario:lista_proveedores", proveedor_id=plantilla.proveedor.id)
    

    # En tu views.py para la vista que renderiza esto
class ProveedorProductosView(DetailView): 
    model = Proveedor
    template_name = 'inventario/proveedores/proveedor_detalle.html' # Nuevo template
    context_object_name = 'proveedor'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Asumiendo que 'producto_set' es el related_name del ForeignKey Producto a Proveedor
        context['productos_del_proveedor'] = self.object.producto_set.all() 
        return context
    

class ProveedorPlantillaView(LoginRequiredMixin, TemplateView):
    template_name = "inventario/proveedores/proveedor_plantilla.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        negocio = self.request.user.perfilusuario.negocio

        proveedor = get_object_or_404(
            Proveedor,
            pk=self.kwargs["pk"],
            negocio=negocio,
        )

        productos = (
            Producto.objects
            .filter(negocio=negocio, proveedor=proveedor, activo=True)
            .order_by("nombre")
        )

        # sugerir cantidad a pedir según stock crítico
        for p in productos:
            falta = max((p.stock_min or 0) - (p.stock_actual or 0), 0)
            p.cantidad_sugerida = falta

        ultima_compra = (
            Compra.objects
            .filter(negocio=negocio, proveedor=proveedor)
            .order_by("-fecha")
            .first()
        )

        context.update(
            proveedor=proveedor,
            productos=productos,
            ultima_compra=ultima_compra,
        )
        return context


@login_required
@rol_requerido("CAJERO", "ADMIN")
def proveedor_plantilla_pdf_view(request, pk):
    """
    Genera un PDF de orden de pedido para el proveedor usando xhtml2pdf.
    Recibe las cantidades por POST.
    Si se pasa preview=1, muestra el HTML en el navegador.
    """
    from io import BytesIO
    from django.http import HttpResponse
    from django.template.loader import get_template
    from xhtml2pdf import pisa
    from datetime import datetime
    import os
    from django.conf import settings

    negocio = request.user.perfilusuario.negocio
    proveedor = get_object_or_404(Proveedor, pk=pk, negocio=negocio)

    # Obtener productos del proveedor
    productos = Producto.objects.filter(
        negocio=negocio, proveedor=proveedor, activo=True
    ).order_by("nombre")

    # Filtrar solo productos con cantidad > 0
    items_pedido = []
    total = 0

    for p in productos:
        cantidad_str = request.POST.get(f"cantidad_{p.id}", "0")
        try:
            cantidad = int(cantidad_str)
        except ValueError:
            cantidad = 0

        if cantidad > 0:
            subtotal = (p.costo or 0) * cantidad
            items_pedido.append({
                "producto": p,
                "cantidad": cantidad,
                "costo": p.costo or 0,
                "subtotal": subtotal,
            })
            total += subtotal

    # Si no hay items, redirigir con mensaje
    if not items_pedido:
        messages.warning(request, "Debes seleccionar al menos un producto con cantidad mayor a 0.")
        return redirect("inventario:proveedor_plantilla", pk=pk)

    # Ruta del logo
    logo_path = os.path.join(settings.STATIC_ROOT or settings.BASE_DIR / 'static', 'img', 'logo_gran_pirula_marron.jpg')
    if not os.path.exists(logo_path):
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'logo_gran_pirula_marron.jpg')

    # Contexto para el PDF
    context = {
        "proveedor": proveedor,
        "negocio": negocio,
        "items": items_pedido,
        "total": total,
        "fecha": datetime.now(),
        "usuario": request.user,
        "logo_path": logo_path,
        "is_preview": request.POST.get("preview") == "1",
    }

    # Si es preview, mostrar HTML en navegador
    if request.POST.get("preview") == "1":
        template = get_template("inventario/proveedores/plantilla_preview.html")
        return HttpResponse(template.render(context, request))

    # Renderizar template PDF
    template = get_template("inventario/proveedores/plantilla_pdf.html")
    html = template.render(context)

    # Crear PDF
    result = BytesIO()
    pdf = pisa.CreatePDF(BytesIO(html.encode("UTF-8")), dest=result)

    if pdf.err:
        return HttpResponse("Error al generar PDF", status=500)

    # Respuesta con PDF
    response = HttpResponse(result.getvalue(), content_type="application/pdf")
    filename = f"pedido_{proveedor.nombre[:20]}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

# ================== CATEGORÍAS (CRUD INTERNO) ======================

class CategoriaListaView(RolRequeridoMixin, ListView):
    roles_requeridos = ["CAJERO", "ADMIN"]
    model = Categoria
    template_name = "inventario/categorias/categoria_lista.html"
    context_object_name = "categorias"
    paginate_by = 25

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return (
            Categoria.objects
            .filter(negocio=negocio)
            .order_by("orden", "nombre")
        )


class CategoriaCrearView(RolRequeridoMixin, CreateView):
    roles_requeridos = ["CAJERO", "ADMIN"]
    model = Categoria
    fields = ["nombre", "imagen", "activo", "orden"]
    template_name = "inventario/categorias/categoria_form.html"
    success_url = reverse_lazy("inventario:categoria_lista")

    def form_valid(self, form):
        form.instance.negocio = self.request.user.perfilusuario.negocio
        return super().form_valid(form)


class CategoriaActualizarView(RolRequeridoMixin, UpdateView):
    roles_requeridos = ["CAJERO", "ADMIN"]
    model = Categoria
    fields = ["nombre", "imagen", "activo", "orden"]
    template_name = "inventario/categorias/categoria_form.html"
    success_url = reverse_lazy("inventario:categoria_lista")

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Categoria.objects.filter(negocio=negocio)


class CategoriaToggleActivaView(RolRequeridoMixin, View):
    roles_requeridos = ["CAJERO", "ADMIN"]
    """
    Soft-delete: sólo cambia 'activa' en vez de borrar.
    """
    def post(self, request, pk):
        negocio = request.user.perfilusuario.negocio
        categoria = get_object_or_404(
            Categoria,
            pk=pk,
            negocio=negocio,
        )
        categoria.activo = not categoria.activo
        categoria.save()
        return redirect("inventario:categoria_lista")


# ================== MARCAS (CRUD INTERNO) ======================

class MarcaListaView(RolRequeridoMixin, ListView):
    roles_requeridos = ["CAJERO", "ADMIN"]
    model = Marca
    template_name = "inventario/marcas/marca_lista.html"
    context_object_name = "marcas"
    paginate_by = 25

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Marca.objects.filter(negocio=negocio).order_by("nombre")


class MarcaCrearView(RolRequeridoMixin, CreateView):
    roles_requeridos = ["CAJERO", "ADMIN"]
    model = Marca
    fields = ["nombre", "imagen", "activo"]
    template_name = "inventario/marcas/marca_form.html"
    success_url = reverse_lazy("inventario:marca_lista")

    def form_valid(self, form):
        form.instance.negocio = self.request.user.perfilusuario.negocio
        return super().form_valid(form)


class MarcaActualizarView(RolRequeridoMixin, UpdateView):
    roles_requeridos = ["CAJERO", "ADMIN"]
    model = Marca
    fields = ["nombre", "imagen", "activo"]
    template_name = "inventario/marcas/marca_form.html"
    success_url = reverse_lazy("inventario:marca_lista")

    def get_queryset(self):
        negocio = self.request.user.perfilusuario.negocio
        return Marca.objects.filter(negocio=negocio)


class MarcaToggleActivaView(RolRequeridoMixin, View):
    roles_requeridos = ["CAJERO", "ADMIN"]

    def post(self, request, pk):
        negocio = request.user.perfilusuario.negocio
        marca = get_object_or_404(Marca, pk=pk, negocio=negocio)
        marca.activo = not marca.activo
        marca.save()
        return redirect("inventario:marca_lista")


# ================== PROMOCIONES / COMBOS ======================

@login_required
def promo_lista_view(request):
    """
    Lista de promociones del negocio actual.
    """
    negocio = request.user.perfilusuario.negocio
    promos = Promo.objects.filter(negocio=negocio).order_by("-activo", "nombre")

    context = {
        "promos": promos,
    }
    return render(request, "inventario/promociones/promo_lista.html", context)


@login_required
def promo_detalle_view(request, pk):
    """
    Vista de detalle de una promoción.
    """
    negocio = request.user.perfilusuario.negocio
    promo = get_object_or_404(Promo, pk=pk, negocio=negocio)

    context = {
        "promo": promo,
    }
    return render(request, "inventario/promociones/promo_detalle.html", context)


@login_required
@rol_requerido("CAJERO", "ADMIN")
def promo_crear_view(request):
    """
    Crear una nueva promo con sus productos (PromoItem).
    """
    negocio = request.user.perfilusuario.negocio

    if request.method == "POST":
        form = PromoForm(request.POST, request.FILES)
        formset = PromoItemFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            promo = form.save(commit=False)
            promo.negocio = negocio
            promo.save()

            formset.instance = promo
            formset.save()
            detalles_registro = {
                'codigo_promo': promo.id, # Asumiendo que existe un campo 'codigo'
                'nombre_promo': promo.nombre, # Asumiendo que existe un campo 'nombre'
                'tipo_descripcion': promo.descripcion,
                'precio_combo':promo.precio_combo, # Asumiendo este campo
                # El número de ítems se puede contar si se necesita:
                # 'items_incluidos': formset.total_form_count(),
            }
            registrar_bitacora_estructurada(
                usuario=request.user,
                accion=f"Creación de Promoción: {promo.id}",
                entidad_id=promo.pk,
                detalles=detalles_registro
            )
            return redirect("inventario:promo_lista")
    else:
        form = PromoForm()
        formset = PromoItemFormSet()

    context = {
        "modo": "crear",
        "form": form,
        "formset": formset,
    }
    return render(request, "inventario/promociones/promo_form.html", context)


@login_required
@rol_requerido("CAJERO", "ADMIN")
def promo_editar_view(request, pk):
    """
    Editar una promo existente y sus productos asociados.
    """
    negocio = request.user.perfilusuario.negocio
    promo = get_object_or_404(Promo, pk=pk, negocio=negocio)

    if request.method == "POST":
        form = PromoForm(request.POST, request.FILES, instance=promo)
        formset = PromoItemFormSet(request.POST, instance=promo)

        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            return redirect("inventario:promo_lista")
    else:
        form = PromoForm(instance=promo)
        formset = PromoItemFormSet(instance=promo)

    context = {
        "modo": "editar",
        "form": form,
        "formset": formset,
        "promo": promo,
    }
    return render(request, "inventario/promociones/promo_form.html", context)


@login_required
@rol_requerido("CAJERO", "ADMIN")
def promo_toggle_activa_view(request, pk):
    """
    Soft-delete: cambia 'activo' en vez de borrar la promo.
    """
    negocio = request.user.perfilusuario.negocio
    promo = get_object_or_404(Promo, pk=pk, negocio=negocio)
    promo.activo = not promo.activo
    promo.save(update_fields=["activo"])
    return redirect("inventario:promo_lista")


# Mermas 

@login_required
@rol_requerido("CAJERO", "ADMIN")
def merma_lista(request):
    negocio = get_negocio_actual(request)

    qs = MovimientoInventario.objects.filter(
        tipo=MovimientoInventario.TIPO_MERMA,
        producto__negocio=negocio,
    ).select_related("producto", "producto__categoria").order_by("-fecha")

    categoria_id = request.GET.get("categoria")
    q = (request.GET.get("q") or "").strip()

    if categoria_id:
        qs = qs.filter(producto__categoria_id=categoria_id)

    if q:
        qs = qs.filter(
            Q(producto__nombre__icontains=q)
            | Q(producto__ean__icontains=q)
            | Q(producto__sku__icontains=q)
        )

    categorias = Categoria.objects.filter(
        negocio=negocio, activo=True
    ).order_by("nombre")

    context = {
        "mermas": qs,
        "categorias": categorias,
        "filtros": {
            "categoria": categoria_id or "",
            "q": q,
        },
    }
    return render(request, "inventario/merma/merma_lista.html", context)


@login_required
@rol_requerido("CAJERO", "ADMIN")
def merma_crear(request):
    negocio = get_negocio_actual(request)

    if request.method == "POST":
        form = MermaForm(request.POST, negocio=negocio)
        if form.is_valid():
            merma = form.save(commit=False)
            merma.tipo = MovimientoInventario.TIPO_MERMA
            merma.usuario = request.user
            merma.save() # Guarda la merma (que es un MovimientoInventario)
            
            producto = merma.producto # Accede al producto afectado por la merma
            
            accion_desc = f"Registro de Merma (Pérdida de Stock) para: {producto.nombre}"
            perfil = request.user
            negocio = perfil.perfilusuario.negocio

            detalles_registro = {
                'producto_afectado_id': producto.pk,
                'producto_nombre': producto.nombre,
                'tipo_movimiento': merma.get_tipo_display(), 
                'cantidad_movida': str(merma.cantidad),
                'comentario_registro': merma.comentario or 'Sin Comentario',
                'usuario_responsable_id': str(request.user.pk),
            }
            tipo_accion="MERMA"
            registrar_bitacora_estructurada(
                negocio=negocio,
                usuario=request.user,
                nombre_modelo='Inventario',
                tipo_accion=tipo_accion, 
                accion=accion_desc,
                entidad_id=merma.pk,
                detalles=detalles_registro
            )

            messages.success(request, "Merma registrada correctamente.")
            return redirect("inventario:merma_lista")
    else:
        form = MermaForm(negocio=negocio)

    return render(request, "inventario/merma/merma_form.html", {"form": form})

@login_required
@rol_requerido("CAJERO", "ADMIN")
def merma_editar(request, pk):
    negocio = get_negocio_actual(request)
    merma = get_object_or_404(
        MovimientoInventario,
        pk=pk,
        tipo=MovimientoInventario.TIPO_MERMA,
        producto__negocio=negocio,
    )

    if request.method == "POST":
        form = MermaForm(request.POST, instance=merma, negocio=negocio)
        if form.is_valid():
            form.instance.tipo = MovimientoInventario.TIPO_MERMA
            form.save()
            messages.success(request, "Merma actualizada.")
            return redirect("inventario:merma_lista")
    else:
        form = MermaForm(instance=merma, negocio=negocio)

    return render(
        request,
        "inventario/merma/merma_form.html",
        {"form": form, "merma": merma},
    )

@login_required
@rol_requerido("CAJERO", "ADMIN")
def merma_eliminar(request, pk):
    negocio = get_negocio_actual(request)
    merma = get_object_or_404(
        MovimientoInventario,
        pk=pk,
        tipo=MovimientoInventario.TIPO_MERMA,
        producto__negocio=negocio,
    )

    if request.method == "POST":
        merma.delete()
        messages.info(request, "Merma eliminada.")
        return redirect("inventario:merma_lista")

    return render(
        request,
        "inventario/merma/merma_confirmar_eliminar.html",
        {"merma": merma},
    )


# --- Sugerencias de productos (autocomplete) ---
@login_required
def sugerencias_productos(request):
    """Endpoint API para autocompletado de productos en compras."""
    negocio = request.user.perfilusuario.negocio
    q = request.GET.get("q", "").strip()
    proveedor_id = request.GET.get("proveedor", "")

    resultados = []
    if len(q) >= 2:
        palabras = q.split()
        
        # Crear query de búsqueda
        query = Q()
        for palabra in palabras:
            query |= (
                Q(nombre__icontains=palabra) |
                Q(sku__icontains=palabra) |
                Q(ean__icontains=palabra) |
                Q(formato__icontains=palabra)
            )
        
        # También buscar la frase completa
        query |= Q(nombre__icontains=q)
        
        productos = Producto.objects.filter(
            negocio=negocio,
            activo=True,
        ).filter(query)
        
        # Filtrar por proveedor si se especifica
        if proveedor_id:
            productos = productos.filter(proveedor_id=proveedor_id)
        
        productos = productos.distinct().order_by("nombre")[:10]

        for p in productos:
            resultados.append({
                "id": p.id,
                "nombre": p.nombre,
                "sku": p.sku or "",
                "ean": p.ean or "",
                "costo": float(p.costo or 0),
            })

    return JsonResponse({"resultados": resultados})
