from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum, Count, F, DecimalField
from django.http import HttpResponse
from django.utils import timezone
from datetime import datetime, timedelta
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth, TruncYear, ExtractHour, ExtractWeekDay

import csv
import json
from ventas.models import Venta, VentaItem
from inventario.models import Categoria, Producto, MovimientoInventario, Proveedor, CompraItem
from django.views import View
from django.shortcuts import render
from pedidos.models import Pedido
from django.conf import settings
from core.utils import render_to_pdf
import os



class ReporteStockQuiebresView(LoginRequiredMixin, TemplateView):
    template_name = "reportes/reporte_quiebres.html"

    def _parse_date(self, value, default):
        if not value:
            return default
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return default

    def _get_filtros(self):
        request = self.request
        hoy = timezone.now().date()

        # Últimos 30 días por defecto
        default_desde = hoy - timedelta(days=30)
        default_hasta = hoy

        desde_str = request.GET.get("desde")
        hasta_str = request.GET.get("hasta")
        categoria_id = request.GET.get("categoria") or ""
        proveedor_id = request.GET.get("proveedor") or ""
        # "critico", "quiebres", "ambos"
        estado = request.GET.get("estado") or "ambos"

        desde = self._parse_date(desde_str, default_desde)
        hasta = self._parse_date(hasta_str, default_hasta)

        # Normalizar: hasta nunca antes que desde y no en el futuro
        hoy_sistema = hoy
        if desde > hoy_sistema:
            desde = hoy_sistema
        if hasta > hoy_sistema:
            hasta = hoy_sistema
        if hasta < desde:
            hasta = desde

        return {
            "desde": desde,
            "hasta": hasta,
            "desde_str": desde.strftime("%Y-%m-%d"),
            "hasta_str": hasta.strftime("%Y-%m-%d"),
            "categoria_id": str(categoria_id),
            "proveedor_id": str(proveedor_id),
            "estado": estado,
        }

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)

        export = request.GET.get("export")
        if export == "pdf":
            return self.export_pdf(request)
        if export == "csv":
            filtros = context.get("filtros", {})
            estado = filtros.get("estado", "ambos")

            productos_criticos = context.get("productos_criticos", [])
            quiebres = context.get("quiebres", [])

            # Respuesta  combinada
            response = HttpResponse(
                content_type="text/csv; charset=utf-8"
            )
            response["Content-Disposition"] = (
                'attachment; filename="stock_critico_quiebres.csv"'
            )

            # BOM para que Excel detecte UTF-8
            response.write("\ufeff")
            writer = csv.writer(response, delimiter=";")

            # STOCK CRÍTICO

            if estado in ("critico", "ambos") and productos_criticos:
                # Título de sección
                writer.writerow(["Productos con stock crítico"])
                # Encabezados
                writer.writerow([
                    "Código",
                    "Nombre",
                    "Categoría",
                    "Proveedor",
                    "Stock actual",
                    "Stock mínimo",
                    "Diferencia",
                    "Estado",
                ])

                for item in productos_criticos:
                    producto = item["producto"]
                    codigo = getattr(
                        producto,
                        "sku",
                        getattr(producto, "ean", producto.pk)
                    )

                    writer.writerow([
                        codigo,
                        producto.nombre,
                        item["categoria"].nombre if item["categoria"] else "",
                        item["proveedor"].nombre if item["proveedor"] else "",
                        item["stock"],
                        item["minimo"],
                        item["diferencia"],
                        "SIN STOCK" if item["sin_stock"] else "CRÍTICO",
                    ])

            # HISTORIAL QUIEBRES
            if estado in ("quiebres", "ambos") and quiebres:
                # Si ya escribimos críticos antes, dejamos una fila en blanco
                if estado == "ambos" and productos_criticos:
                    writer.writerow([])

                writer.writerow(["Historial de quiebres"])
                writer.writerow([
                    "Producto",
                    "Categoría",
                    "Proveedor",
                    "Motivo",
                    "Fecha quiebre",
                    "Fecha reposición",
                    "Duración (días)",
                    "N° quiebres en el período",
                ])

                for item in quiebres:
                    producto = item["producto"]
                    categoria = getattr(
                        producto.categoria, "nombre", ""
                    ) if getattr(producto, "categoria_id", None) else ""
                    proveedor = getattr(
                        producto.proveedor, "nombre", ""
                    ) if getattr(producto, "proveedor_id", None) else ""

                    fecha_quiebre = item["fecha_quiebre"]
                    fecha_reposicion = item.get("fecha_reposicion")
                    duracion = item.get("duracion")
                    total_quiebres = item.get("total_quiebres_producto", 0)
                    motivo = item.get("motivo", "")

                    writer.writerow([
                        producto.nombre,
                        categoria,
                        proveedor,
                        motivo,
                        fecha_quiebre.strftime("%d-%m-%Y"),
                        fecha_reposicion.strftime(
                            "%d-%m-%Y") if fecha_reposicion else "Sin reposición registrada",
                        duracion if duracion is not None else "-",
                        total_quiebres,
                    ])

            return response

        # Render normal (HTML)
        return self.render_to_response(context)


    def export_pdf(self, request):
        context = self.get_context_data()
        context["user"] = request.user
        context["logo_path"] = "img/logo_gran_pirula_marron.jpg"
        filename = f"reporte_quiebres_{timezone.now().strftime('%Y%m%d')}.pdf"
        response = render_to_pdf("reportes/pdf/quiebres_pdf.html", context)
        if response.status_code == 200:
             response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filtros = self._get_filtros()
        request = self.request

        negocio = request.user.perfilusuario.negocio

        # Catálogos base
        categorias_qs = Categoria.objects.filter(
            negocio=negocio
        )
        proveedores_qs = Proveedor.objects.filter(
            negocio=negocio
        )

        categoria_id = filtros["categoria_id"]
        proveedor_id = filtros["proveedor_id"]

        #limita proveedores
        if categoria_id:
            proveedores_qs = proveedores_qs.filter(
                producto__negocio=negocio,
                producto__categoria_id=categoria_id,
            ).distinct()

        # limita categorías
        if proveedor_id:
            categorias_qs = categorias_qs.filter(
                producto__negocio=negocio,
                producto__proveedor_id=proveedor_id,
            ).distinct()

        categorias = categorias_qs.order_by("nombre")
        proveedores = proveedores_qs.order_by("nombre")

        productos_qs = Producto.objects.filter(
            negocio=negocio,
            activo=True
        ).select_related("categoria", "proveedor")

        if categoria_id:
            productos_qs = productos_qs.filter(categoria_id=categoria_id)

        if proveedor_id:
            productos_qs = productos_qs.filter(proveedor_id=proveedor_id)

        # ---  Productos con stock crítico ---
        productos_criticos = []

        for p in productos_qs:

            stock_actual = getattr(p, "stock_actual", None)
            if stock_actual is None:
                stock_actual = getattr(p, "stock", 0)

            stock_minimo = getattr(p, "stock_min", None)
            if stock_minimo is None:
                stock_minimo = getattr(p, "stock_minimo", 0)

            stock_minimo = stock_minimo or 0

            sin_stock = stock_actual <= 0
            critico = (stock_actual > 0) and (stock_actual <= stock_minimo)

            if not (sin_stock or critico):
                # No está en nivel crítico, omitimos
                continue

            ultima_compra = None
            dias_sin_compra = None

            productos_criticos.append({
                "producto": p,
                "categoria": p.categoria,
                "proveedor": p.proveedor,
                "stock": stock_actual,
                "minimo": stock_minimo,
                "diferencia": max(0, stock_minimo - stock_actual),
                "sin_stock": sin_stock,
                "critico": critico,
                "ultima_compra": ultima_compra,
                "dias_sin_compra": dias_sin_compra,
            })

        # Ordenar por criticidad (mayor falta primero, y sin stock al tope)
        productos_criticos.sort(
            key=lambda x: (0 if x["sin_stock"] else 1, -x["diferencia"])
        )

        # --- Historial de quiebres de stock (cuando el stock llega a 0) ---
        desde = filtros["desde"]
        hasta = filtros["hasta"]

        # Para calcular quiebres de stock, necesitamos analizar los movimientos
        # y detectar cuándo el stock resultante de un producto llegó a 0
        quiebres = []
        quiebres_por_producto = {}

        for producto in productos_qs:
            # Obtener stock actual del producto
            stock_actual = getattr(producto, "stock_actual", None)
            if stock_actual is None:
                stock_actual = getattr(producto, "stock", 0) or 0

            # Obtener todos los movimientos del producto en el período, ordenados por fecha
            movimientos = (
                MovimientoInventario.objects
                .filter(
                    producto=producto,
                    fecha__date__gte=desde,
                    fecha__date__lte=hasta,
                )
                .order_by("fecha", "id")
            )

            # Calcular el stock al inicio del período (stock actual - cambios del período hasta ahora)
            # Suma de entradas y ajustes positivos, resta de salidas y mermas
            for mov in movimientos:
                if mov.tipo in [MovimientoInventario.TIPO_ENTRADA]:
                    stock_actual -= mov.cantidad  # Revertimos para calcular stock inicial
                elif mov.tipo in [MovimientoInventario.TIPO_SALIDA, MovimientoInventario.TIPO_MERMA]:
                    stock_actual += mov.cantidad  # Revertimos
                elif mov.tipo == MovimientoInventario.TIPO_AJUSTE:
                    # Los ajustes pueden ser positivos o negativos
                    # Asumimos que cantidad es el valor absoluto del ajuste
                    pass  # Esto es más complejo, por ahora simplificamos

            stock_corriente = stock_actual

            # Ahora recorremos los movimientos y detectamos quiebres
            for mov in movimientos:
                # Aplicar el movimiento
                if mov.tipo == MovimientoInventario.TIPO_ENTRADA:
                    stock_corriente += mov.cantidad
                elif mov.tipo in [MovimientoInventario.TIPO_SALIDA, MovimientoInventario.TIPO_MERMA]:
                    stock_corriente -= mov.cantidad
                elif mov.tipo == MovimientoInventario.TIPO_AJUSTE:
                    # Para ajustes, asumimos que el stock se establece o ajusta
                    pass

                # Si el stock llega a 0 o menos después de este movimiento, es un quiebre
                if stock_corriente <= 0:
                    fecha_quiebre = mov.fecha.date()

                    # Buscar la siguiente entrada como reposición
                    siguiente_mov = (
                        MovimientoInventario.objects
                        .filter(
                            producto=producto,
                            fecha__gt=mov.fecha,
                            tipo=MovimientoInventario.TIPO_ENTRADA,
                        )
                        .order_by("fecha")
                        .first()
                    )

                    if siguiente_mov:
                        fecha_reposicion = siguiente_mov.fecha.date()
                        duracion = (fecha_reposicion - fecha_quiebre).days
                    else:
                        fecha_reposicion = None
                        duracion = None

                    # Solo agregar si no hay ya un quiebre muy reciente del mismo producto
                    ya_registrado = any(
                        q["producto"].id == producto.id and q["fecha_quiebre"] == fecha_quiebre
                        for q in quiebres
                    )

                    if not ya_registrado:
                        quiebres.append({
                            "producto": producto,
                            "fecha_quiebre": fecha_quiebre,
                            "fecha_reposicion": fecha_reposicion,
                            "duracion": duracion,
                            "motivo": f"Stock llegó a 0 después de {mov.get_tipo_display()}",
                        })

                        quiebres_por_producto[producto.id] = (
                            quiebres_por_producto.get(producto.id, 0) + 1
                        )

        # Ordenar quiebres por fecha descendente
        quiebres.sort(key=lambda x: x["fecha_quiebre"], reverse=True)

        # Anotar cantidad de quiebres por producto
        for q in quiebres:
            q["total_quiebres_producto"] = quiebres_por_producto.get(
                q["producto"].id, 0
            )

        # Si el estado es critico, ocultamos la tabla de quiebres
        estado = filtros["estado"]

        # Para la tabla de productos críticos
        if estado == "quiebres":
            #Solo quiebre
            productos_criticos_mostrar = []
        else:
            productos_criticos_mostrar = productos_criticos


        if estado == "critico":
            # Solo stock crítico
            quiebres_mostrar = []
        else:
            quiebres_mostrar = quiebres

        # Mensaje si no hay nada que mostrar en ninguna tabla
        hay_datos = bool(productos_criticos_mostrar or quiebres_mostrar)
        hoy_sistema = timezone.now().date()

        context.update({
            "filtros": filtros,
            "categorias": categorias,
            "proveedores": proveedores,
            "productos_criticos": productos_criticos_mostrar,
            "quiebres": quiebres_mostrar,
            "hay_datos": hay_datos,
            "hoy_sistema": hoy_sistema,
        })
        return context


class ReporteVentasView(LoginRequiredMixin, TemplateView):
    template_name = "reportes/ventas.html"

    def _get_ventas_filtradas(self, request):
        negocio = request.user.perfilusuario.negocio
        hoy_sistema = timezone.localtime(timezone.now()).date()  # fecha real de hoy (Local)

        ventas = Venta.objects.filter(
            negocio=negocio,
            estado=Venta.EST_CERRADA,
        )

        desde_str = request.GET.get("desde")
        hasta_str = request.GET.get("hasta")
        medio = request.GET.get("medio") or ""
        categoria_id = request.GET.get("categoria") or ""

        # PARSEO DE FECHAS
        if desde_str:
            try:
                desde = datetime.strptime(desde_str, "%Y-%m-%d").date()
            except ValueError:
                desde = hoy_sistema.replace(day=1)
        else:
            # por defecto, primer día del mes actual
            desde = hoy_sistema.replace(day=1)

        if hasta_str:
            try:
                hasta = datetime.strptime(hasta_str, "%Y-%m-%d").date()
            except ValueError:
                hasta = hoy_sistema
        else:
            # por defecto, hoy
            hasta = hoy_sistema

        # Ninguna fecha puede ser futura
        if desde > hoy_sistema:
            desde = hoy_sistema
        if hasta > hoy_sistema:
            hasta = hoy_sistema

        # "Hasta" nunca puede ser menor que "Desde"
        if hasta < desde:
            hasta = desde

        # APLICAR FILTROS
        ventas = ventas.filter(fecha__date__gte=desde, fecha__date__lte=hasta)

        if medio:
            ventas = ventas.filter(medio_pago=medio)

        if categoria_id:
            venta_ids = (
                VentaItem.objects
                .filter(producto__categoria_id=categoria_id)
                .values_list("venta_id", flat=True)
            )
            ventas = ventas.filter(id__in=venta_ids)

        # Fecha de referencia para "ventas hoy" y textos
        dia_ref = hasta or hoy_sistema

        return ventas.distinct(), desde, hasta, medio, categoria_id, negocio, dia_ref

    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv":
            return self.exportar_csv(request)
        if request.GET.get("export") == "pdf":
            return self.export_pdf(request)
        return super().get(request, *args, **kwargs)

    def export_pdf(self, request):
        # Para obtener el contexto completo calculamos primero todo
        # Aprovechamos get_context_data que ya hace todo el trabajo pesado
        # Pasamos kwargs vacíos o lo que requiera
        context = self.get_context_data()
        context["user"] = request.user
        context["logo_path"] = "img/logo_gran_pirula_marron.jpg"
        filename = f"reporte_ventas_{timezone.now().strftime('%Y%m%d')}.pdf"
        response = render_to_pdf("reportes/pdf/ventas_pdf.html", context)
        if response.status_code == 200:
            response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response


    # ----------------- Exportar CSV -----------------


    def exportar_csv(self, request):

        ventas_filtradas, _, _, _, _, _, _ = self._get_ventas_filtradas(
            request)

        # Ítems de esas ventas, con producto y categoría
        items = (
            VentaItem.objects
            .filter(venta__in=ventas_filtradas)
            .select_related("venta", "producto", "producto__categoria")
            .order_by("venta__fecha", "venta_id")
        )

        # Respuesta CSV
        response = HttpResponse(
            content_type="text/csv; charset=utf-8"
        )
        response["Content-Disposition"] = 'attachment; filename="reporte_ventas_items.csv"'
        response.write("\ufeff")  # BOM para que Excel muestre bien los acentos

        writer = csv.writer(response, delimiter=";")

        # Encabezados
        writer.writerow([
            "Fecha",
            "Hora",
            "ID venta",
            "Medio de pago",
            "Producto",
            "Categoría",
            "Cantidad",
            "Precio unitario",
            "Total ítem",
            "Total venta",
        ])

        # UNA por item vendido
        for item in items:
            venta = item.venta
            producto = item.producto
            categoria = getattr(producto.categoria, "nombre", "") if getattr(
                producto, "categoria_id", None) else ""

            total_item = item.cantidad * item.precio_unit

            # Intentamos usar propiedad total de la venta 
            venta_total = getattr(venta, "total", None)
            if venta_total is None:
                # Si no hay propiedad total en el modelo, calculamos a mano
                venta_total = sum(
                    it.cantidad * it.precio_unit
                    for it in venta.items.all()
                )

            writer.writerow([
                venta.fecha.strftime("%d-%m-%Y"),
                venta.fecha.strftime("%H:%M"),
                venta.id,
                venta.get_medio_pago_display(),
                producto.nombre,
                categoria,
                item.cantidad,
                item.precio_unit,
                venta_total,
            ])

        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request = self.request

        hoy_sistema = timezone.localtime(timezone.now()).date()  

        ventas_filtradas, desde, hasta, medio, categoria_id, negocio, dia_ref = \
            self._get_ventas_filtradas(request)

        # --------- VENTAS DEL DIA ----------

        ventas_hoy = ventas_filtradas.filter(fecha__date=dia_ref)
        total_hoy = sum(v.total for v in ventas_hoy)

        # --------- KPIs DEL PERÍODO FILTRADO ----------
        total_periodo = sum(v.total for v in ventas_filtradas)
        cant_ventas_periodo = ventas_filtradas.count()
        ticket_promedio_periodo = (
            total_periodo / cant_ventas_periodo if cant_ventas_periodo else 0
        )

        pagos = (
            VentaItem.objects
            .filter(venta__in=ventas_filtradas)
            .values("venta__medio_pago")
            .annotate(
                medio_pago=F("venta__medio_pago"),
                total=Sum(
                    F("cantidad") * F("precio_unit"),
                    output_field=DecimalField(max_digits=12, decimal_places=0),
                ),
                cantidad=Count("venta", distinct=True),
            )
            .values("medio_pago", "total", "cantidad")
            .order_by("medio_pago")
        )

        top_productos = (
            VentaItem.objects
            .filter(venta__in=ventas_filtradas)
            .values("producto__nombre")
            .annotate(
                unidades=Sum("cantidad"),
                total=Sum(
                    F("cantidad") * F("precio_unit"),
                    output_field=DecimalField(max_digits=12, decimal_places=0),
                ),
            )
            .order_by("-unidades")[:10]
        )

        items_filtrados = VentaItem.objects.filter(venta__in=ventas_filtradas)

        # Día
        ventas_por_dia = (
            items_filtrados
            .annotate(dia=TruncDay("venta__fecha"))
            .values("dia")
            .annotate(
                total=Sum(
                    F("cantidad") * F("precio_unit"),
                    output_field=DecimalField(max_digits=12, decimal_places=0),
                ),
            )
            .order_by("dia")
        )
        day_labels = [v["dia"].strftime("%d-%m") for v in ventas_por_dia]
        day_data = [int(v["total"] or 0) for v in ventas_por_dia]

        # Mes
        ventas_por_mes = (
            items_filtrados
            .annotate(mes=TruncMonth("venta__fecha"))
            .values("mes")
            .annotate(
                total=Sum(
                    F("cantidad") * F("precio_unit"),
                    output_field=DecimalField(max_digits=12, decimal_places=0),
                ),
            )
            .order_by("mes")
        )
        month_labels = [v["mes"].strftime("%b %Y") for v in ventas_por_mes]
        month_data = [int(v["total"] or 0) for v in ventas_por_mes]

        # Año
        ventas_por_anio = (
            items_filtrados
            .annotate(anio=TruncYear("venta__fecha"))
            .values("anio")
            .annotate(
                total=Sum(
                    F("cantidad") * F("precio_unit"),
                    output_field=DecimalField(max_digits=12, decimal_places=0),
                ),
            )
            .order_by("anio")
        )
        year_labels = [str(v["anio"].year) for v in ventas_por_anio]
        year_data = [int(v["total"] or 0) for v in ventas_por_anio]

        chart_data = {
            "day": {"labels": day_labels, "data": day_data},
            "month": {"labels": month_labels, "data": month_data},
            "year": {"labels": year_labels, "data": year_data},
        }
        chart_data_json = json.dumps(chart_data)

        #   KPIs Año vs Año (ventas totales del año completo)
        anio_actual = dia_ref.year
        anio_anterior = dia_ref.year - 1

        items_anio_actual = VentaItem.objects.filter(
            venta__negocio=negocio,
            venta__estado=Venta.EST_CERRADA,
            venta__fecha__year=anio_actual,
        )
        total_anio_actual = (
            items_anio_actual
            .aggregate(
                total=Sum(
                    F("cantidad") * F("precio_unit"),
                    output_field=DecimalField(max_digits=14, decimal_places=0),
                )
            )["total"] or 0
        )

        items_anio_anterior = VentaItem.objects.filter(
            venta__negocio=negocio,
            venta__estado=Venta.EST_CERRADA,
            venta__fecha__year=anio_anterior,
        )
        total_anio_anterior = (
            items_anio_anterior
            .aggregate(
                total=Sum(
                    F("cantidad") * F("precio_unit"),
                    output_field=DecimalField(max_digits=14, decimal_places=0),
                )
            )["total"] or 0
        )

        diff_abs = total_anio_actual - total_anio_anterior
        diff_pct = (diff_abs / total_anio_anterior) * \
            100 if total_anio_anterior else 0

        # ----------------- Actualizar contexto -----------------
        context.update({
            # Filtros activos
            "desde": desde,
            "hasta": hasta,
            "medio_seleccionado": medio,
            "categoria_seleccionada": int(categoria_id) if categoria_id else None,
            "hoy": dia_ref,
            "hoy_sistema": hoy_sistema,
            "medios_pago": Venta.MEDIO_PAGO_CHOICES,
            "categorias": Categoria.objects.filter(negocio=negocio),

            # Tarjetas
            "ventas_hoy": ventas_hoy,
            "total_hoy": total_hoy,
            "ventas_mes": ventas_filtradas,          
            "total_mes": total_periodo,
            "ticket_promedio_mes": ticket_promedio_periodo,

            # Tablas
            "pagos": pagos,
            "top_productos": top_productos,


            # Datos para el gráfico
            "chart_data_json": chart_data_json,

            # KPIs año vs año
            "anio_actual": anio_actual,
            "anio_anterior": anio_anterior,
            "ventas_anio_actual": total_anio_actual,
            "ventas_anio_anterior": total_anio_anterior,
            "ventas_yoy_abs": diff_abs,
            "ventas_yoy_pct": diff_pct,
        })
        return context



class ReporteNoRetiraView(LoginRequiredMixin, TemplateView):
    template_name = "reportes/no_retira.html"

    def _get_datos_base(self, request):
        negocio = request.user.perfilusuario.negocio
        hoy_sistema = timezone.now().date()

        # ----- Filtros -----
        desde_str = (request.GET.get("desde") or "").strip()
        hasta_str = (request.GET.get("hasta") or "").strip()
        canal = (request.GET.get("canal") or "TODOS").strip()
        monto_min_str = (request.GET.get("monto_min") or "").strip()

        # Rango por defecto 30 días
        default_desde = hoy_sistema - timedelta(days=30)
        default_hasta = hoy_sistema

        # Parseo de fechas
        def _parse_date(value, default):
            if not value:
                return default
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                return default

        desde = _parse_date(desde_str, default_desde)
        hasta = _parse_date(hasta_str, default_hasta)

        # Protección para el calendario nada en el futuro y hasta >= desde
        if desde > hoy_sistema:
            desde = hoy_sistema
        if hasta > hoy_sistema:
            hasta = hoy_sistema
        if hasta < desde:
            hasta = desde

        # ----- Query base sobre PEDIDOS -----
        pedidos_qs = (
            Pedido.objects
            .filter(
                negocio=negocio,
                fecha__date__gte=desde,
                fecha__date__lte=hasta,
            )
            .select_related("cliente")
        )

        # Si el Pedido tiene un campo "canal", se usa directo.
        if canal and canal != "TODOS":
            if hasattr(Pedido, "canal"):
                pedidos_qs = pedidos_qs.filter(canal=canal)
            else:
                # Ajusta estos valores a tus choices reales de forma_pago
                if canal.upper() == "ONLINE":
                    pedidos_qs = pedidos_qs.filter(
                        forma_pago=Pedido.FORMA_WEBPAY
                    )
                elif canal.upper() == "MOSTRADOR":
                    pedidos_qs = pedidos_qs.filter(
                        forma_pago=Pedido.FORMA_RETIRO
                    )

        # ----- Filtro por monto minimo -----
        monto_min = None
        if monto_min_str:
            try:
                monto_min = int(monto_min_str)
                pedidos_qs = pedidos_qs.filter(total_monto__gte=monto_min)
            except ValueError:
                monto_min = None  

        total_pedidos = pedidos_qs.count()

        # ----- Pedidos con estado No retira o Cancelado -----
        estados_filtro = [
            getattr(Pedido, "EST_NO_RETIRA", "NO_RETIRA"),
            getattr(Pedido, "EST_CANCELADO", "CANCELADO")
        ]
        pedidos_no_retirados = pedidos_qs.filter(estado__in=estados_filtro)

        total_no_retirados = pedidos_no_retirados.count()

        # Monto perdido por no retiro
        monto_no_retirado = (
            pedidos_no_retirados.aggregate(
                total=Sum("total_monto")
            )["total"] or 0
        )

        # Tasa por no retiro
        tasa_no_retira = (
            (total_no_retirados / total_pedidos) * 100
            if total_pedidos
            else 0
        )

        # Detalle para la tabla y CSV
        detalle = pedidos_no_retirados.order_by("-fecha")

        return {
            "desde": desde,
            "hasta": hasta,
            "desde_str": desde.strftime("%Y-%m-%d"),
            "hasta_str": hasta.strftime("%Y-%m-%d"),
            "hoy_sistema": hoy_sistema,
            "canal": canal or "TODOS",
            "monto_min": monto_min_str or "",
            "total_pedidos": total_pedidos,
            "total_no_retirados": total_no_retirados,
            "tasa_no_retira": tasa_no_retira,
            "monto_no_retirado": monto_no_retirado,
            "detalle_no_retirados": detalle,
        }


    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv":
            return self.export_csv(request)
        if request.GET.get("export") == "pdf":
            return self.export_pdf(request)
        return super().get(request, *args, **kwargs)

    def export_pdf(self, request):
        context = self.get_context_data()
        context["user"] = request.user
        context["logo_path"] = "img/logo_gran_pirula_marron.jpg"
        filename = f"reporte_no_retira_{timezone.now().strftime('%Y%m%d')}.pdf"
        response = render_to_pdf("reportes/pdf/no_retira_pdf.html", context)
        if response.status_code == 200:
            response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response

    # ------------------ contexto ------------------
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        datos = self._get_datos_base(self.request)

        context.update({
            "desde": datos["desde"],
            "hasta": datos["hasta"],
            "desde_str": datos["desde_str"],
            "hasta_str": datos["hasta_str"],
            "hoy_sistema": datos["hoy_sistema"],
            "canal": datos["canal"],
            "monto_min": datos["monto_min"],
            "total_pedidos": datos["total_pedidos"],
            "total_no_retirados": datos["total_no_retirados"],
            "tasa_no_retira": datos["tasa_no_retira"],
            "monto_no_retirado": datos["monto_no_retirado"],
            "detalle_no_retirados": datos["detalle_no_retirados"],
        })
        return context

    # ------------------ EXPORT CSV ------------------
    def export_csv(self, request):
        datos = self._get_datos_base(request)
        pedidos = datos["detalle_no_retirados"]

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        filename = f"reporte_no_retira_{datos['desde']}_a_{datos['hasta']}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        # BOM para que Excel lea bien UTF-8
        response.write("\ufeff")

        writer = csv.writer(response, delimiter=";")

        # Encabezados (solo lo que realmente tenemos)
        writer.writerow([
            "N° pedido",
            "Fecha creación",
            "Monto total",
            "Cliente",
            "Canal",
        ])

        def fmt_fecha(value):
            """Formatea la fecha de creación del pedido."""
            if not value:
                return ""
            try:
                return value.strftime("%d-%m-%Y %H:%M")
            except Exception:
                return str(value)

        for p in pedidos:
            # Monto total (usa total_monto si existe, si no total)
            monto = getattr(p, "total_monto", None) or getattr(
                p, "total", "") or ""

            # Cliente
            if getattr(p, "cliente_id", None):
                cliente = str(p.cliente)
            else:
                cliente = getattr(p, "nombre", "") or "-"

            # Canal
            if hasattr(p, "canal"):
                canal_val = getattr(p, "canal", "") or "-"
            else:
                forma_pago = getattr(p, "forma_pago", "")
                canal_val = (
                    "ONLINE" if forma_pago == getattr(Pedido, "FORMA_WEBPAY", None)
                    else "MOSTRADOR" if forma_pago == getattr(Pedido, "FORMA_RETIRO", None)
                    else "-"
                )

            writer.writerow([
                p.id,
                # ← fecha creación del pedido
                fmt_fecha(getattr(p, "fecha", None)),
                monto,
                cliente,
                canal_val,
            ])

        return response


class ReporteMermasProveedorView(LoginRequiredMixin, TemplateView):
    template_name = "reportes\mermas_proveedor.html"

    # --------- Filtros base ---------
    def _get_filtros(self):
        request = self.request
        hoy = timezone.now().date()
        default_desde = hoy - timedelta(days=30)
        default_hasta = hoy

        desde_str = (request.GET.get("desde") or "").strip()
        hasta_str = (request.GET.get("hasta") or "").strip()
        proveedor_id = (request.GET.get("proveedor") or "").strip()
        categoria_id = (request.GET.get("categoria") or "").strip()

        def _parse_date(value, default):
            if not value:
                return default
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                return default

        desde = _parse_date(desde_str, default_desde)
        hasta = _parse_date(hasta_str, default_hasta)

        return {
            "desde": desde,
            "hasta": hasta,
            "desde_str": desde.strftime("%Y-%m-%d"),
            "hasta_str": hasta.strftime("%Y-%m-%d"),
            "proveedor_id": int(proveedor_id) if proveedor_id else None,
            "categoria_id": int(categoria_id) if categoria_id else None,
        }

    # --------- 2) Obtener datos crudos (compras + mermas) ---------
    def _get_qs(self, filtros):
        negocio = getattr(self.request.user.perfilusuario, 'negocio', None)
        if not negocio:
            return CompraItem.objects.none(), MovimientoInventario.objects.none(), MovimientoInventario.objects.none()

        desde = filtros["desde"]
        hasta = filtros["hasta"]

        # Compras en el período
        compras_qs = CompraItem.objects.filter(
            compra__negocio=negocio,
            compra__fecha__date__gte=desde,
            compra__fecha__date__lte=hasta,
        ).select_related("compra__proveedor", "producto")

        # Mermas en el período
        mermas_qs = MovimientoInventario.objects.filter(
            producto__negocio=negocio,
            tipo=MovimientoInventario.TIPO_MERMA,
            fecha__date__gte=desde,
            fecha__date__lte=hasta,
        ).select_related("producto", "producto__proveedor", "producto__categoria")

        # Filtro por proveedor
        if filtros["proveedor_id"]:
            compras_qs = compras_qs.filter(
                compra__proveedor_id=filtros["proveedor_id"])
            mermas_qs = mermas_qs.filter(
                producto__proveedor_id=filtros["proveedor_id"])

        # Filtro por categoría
        if filtros["categoria_id"]:
            compras_qs = compras_qs.filter(
                producto__categoria_id=filtros["categoria_id"])
            mermas_qs = mermas_qs.filter(
                producto__categoria_id=filtros["categoria_id"])

        # Separar mermas de proveedor (es_quiebre=False) de quiebres internos (es_quiebre=True)
        mermas_proveedor_qs = mermas_qs.filter(es_quiebre=False)
        quiebres_qs = mermas_qs.filter(es_quiebre=True)
        
        return compras_qs, mermas_proveedor_qs, quiebres_qs

    # --------- 3) Armar estructuras para el template y CSV ---------
    def _build_data(self):
        filtros = self._get_filtros()
        compras_qs, mermas_proveedor_qs, quiebres_qs = self._get_qs(filtros)
        negocio = getattr(self.request.user.perfilusuario, 'negocio', None)


        # --- 3.1 Resumen por proveedor (mermas de proveedor) ---

        # Total comprado por proveedor en el período
        compras_agg = compras_qs.values(
            "compra__proveedor_id",
            "compra__proveedor__nombre",
        ).annotate(
            monto_comprado=Sum(F("cantidad") * F("costo_unit"))
        )

        compras_map = {
            row["compra__proveedor_id"]: row for row in compras_agg
        }

        # Total de merma por proveedor (usamos costo del producto)
        mermas_agg = mermas_proveedor_qs.values(
            "producto__proveedor_id",
            "producto__proveedor__nombre",
        ).annotate(
            cantidad_merma=Sum("cantidad"),
            monto_merma=Sum(F("cantidad") * F("producto__costo")),
        )

        mermas_map = {
            row["producto__proveedor_id"]: row for row in mermas_agg
        }

        resumen = []
        proveedor_ids = set(compras_map.keys()) | set(mermas_map.keys())

        for prov_id in proveedor_ids:
            nombre = (
                (compras_map.get(prov_id) or {}).get(
                    "compra__proveedor__nombre")
                or (mermas_map.get(prov_id) or {}).get("producto__proveedor__nombre")
                or "Sin nombre"
            )
            monto_comprado = compras_map.get(
                prov_id, {}).get("monto_comprado", 0) or 0
            monto_merma = mermas_map.get(
                prov_id, {}).get("monto_merma", 0) or 0
            cant_merma = mermas_map.get(prov_id, {}).get(
                "cantidad_merma", 0) or 0

            if monto_comprado > 0:
                porcentaje = round((monto_merma / monto_comprado) * 100, 2)
            else:
                porcentaje = None

            resumen.append({
                "proveedor_id": prov_id,
                "proveedor": nombre,
                "monto_comprado": int(monto_comprado),
                "monto_merma": int(monto_merma),
                "cantidad_merma": cant_merma,
                "porcentaje_merma": porcentaje,
            })

        # Ordenar de mayor a menor porcentaje de merma
        resumen.sort(key=lambda r: (r["porcentaje_merma"] or 0), reverse=True)

        # --- 3.2 Detalle de mermas de proveedor ---
        detalle = []

        for m in mermas_proveedor_qs.select_related(
            "producto",
            "producto__proveedor",
            "producto__categoria",
        ).order_by("-fecha"):

            producto = m.producto
            proveedor = getattr(producto, "proveedor", None)
            categoria = getattr(producto, "categoria", None)

            # si no hay costo, lo dejamos en 0
            costo_unit = (getattr(producto, "costo", 0) or 0)
            monto_merma = m.cantidad * costo_unit

            detalle.append({
                "fecha": m.fecha,
                "proveedor": proveedor.nombre if proveedor else "Sin proveedor",
                "producto": producto.nombre if producto else "",
                "categoria": categoria.nombre if categoria else "",
                "cantidad": m.cantidad,
                "unidad": getattr(producto, "unidad_de_venta", "") or "",
                "motivo": m.comentario or "",
                "costo_unit": costo_unit,
                "monto_merma": monto_merma,
            })

        # --- 3.3 Detalle de quiebres internos ---
        detalle_quiebres = []
        total_monto_quiebres = 0

        for m in quiebres_qs.select_related(
            "producto",
            "producto__proveedor",
            "producto__categoria",
        ).order_by("-fecha"):

            producto = m.producto
            proveedor = getattr(producto, "proveedor", None)
            categoria = getattr(producto, "categoria", None)

            costo_unit = (getattr(producto, "costo", 0) or 0)
            monto_merma = m.cantidad * costo_unit
            total_monto_quiebres += monto_merma

            detalle_quiebres.append({
                "fecha": m.fecha,
                "proveedor": proveedor.nombre if proveedor else "Sin proveedor",
                "producto": producto.nombre if producto else "",
                "categoria": categoria.nombre if categoria else "",
                "cantidad": m.cantidad,
                "unidad": getattr(producto, "unidad_de_venta", "") or "",
                "motivo": m.comentario or "",
                "costo_unit": costo_unit,
                "monto_merma": monto_merma,
            })

        # --- 3.4 Catálogos para filtros ---
        proveedores = Proveedor.objects.none()
        categorias = Categoria.objects.none()
        
        if negocio:
            proveedores = Proveedor.objects.filter(
                negocio=negocio, activo=True
            ).order_by("nombre")

            categorias = Categoria.objects.filter(
                negocio=negocio, activo=True
            ).order_by("nombre")

        return {
            "resumen_proveedores": resumen,
            "detalle_mermas": detalle,
            "detalle_quiebres": detalle_quiebres,
            "total_monto_quiebres": total_monto_quiebres,
            "proveedores": proveedores,
            "categorias": categorias,
            "filtros": filtros,
        }

    # --------- 4) Exportar a CSV ---------
    def _export_csv(self, data):
        filtros = data["filtros"]
        filename = f"mermas_por_proveedor_{filtros['desde_str']}_al_{filtros['hasta_str']}.csv"

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        writer = csv.writer(response)

        # Sección resumen
        writer.writerow(["Resumen de mermas por proveedor"])
        writer.writerow([
            "Proveedor",
            "Monto comprado",
            "Monto en merma",
            "Cantidad en merma",
            "% Merma",
        ])
        for row in data["resumen_proveedores"]:
            writer.writerow([
                row["proveedor"],
                row["monto_comprado"],
                row["monto_merma"],
                row["cantidad_merma"],
                row["porcentaje_merma"] if row["porcentaje_merma"] is not None else "",
            ])

        writer.writerow([])
        writer.writerow(["Detalle de mermas"])
        writer.writerow([
            "Fecha",
            "Proveedor",
            "Producto",
            "Categoría",
            "Cantidad",
            "Unidad",
            "Motivo",
            "Costo unitario",
            "Monto merma",
        ])

        for d in data["detalle_mermas"]:
            writer.writerow([
                d["fecha"].strftime("%Y-%m-%d %H:%M"),
                d["proveedor"],
                d["producto"],
                d["categoria"],
                d["cantidad"],
                d["unidad"],
                d["motivo"],
                d["costo_unit"],
                d["monto_merma"],
            ])

        return response

    def export_pdf(self, data):
        # data ya tiene las estructuras listas
        context = self.get_context_data(**data)
        context["user"] = self.request.user
        context["logo_path"] = "img/logo_gran_pirula_marron.jpg"
        filename = f"reporte_mermas_{timezone.now().strftime('%Y%m%d')}.pdf"
        response = render_to_pdf("reportes/pdf/mermas_pdf.html", context)
        if response.status_code == 200:
            response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response

    # --------- 5) GET: HTML o CSV ---------
    def get(self, request, *args, **kwargs):
        data = self._build_data()

        if request.GET.get("export") == "csv":
            return self._export_csv(data)
        
        if request.GET.get("export") == "pdf":
            return self.export_pdf(data)

        context = self.get_context_data(**data)
        return self.render_to_response(context)


class ReporteDiaHoraView(LoginRequiredMixin, TemplateView):
    template_name = "reportes/dia_hora.html"

    DIA_SEMANA_LABELS = {
        1: "Domingo",
        2: "Lunes",
        3: "Martes",
        4: "Miércoles",
        5: "Jueves",
        6: "Viernes",
        7: "Sábado",
    }

    def get(self, request, *args, **kwargs):
        # sirve para la exportación
        if request.GET.get("export") == "csv":
            return self.export_csv(request)
        if request.GET.get("export") == "pdf":
            return self.export_pdf(request)
        return super().get(request, *args, **kwargs)

    def export_pdf(self, request):
        context = self.get_context_data()
        context["user"] = request.user
        context["logo_path"] = "img/logo_gran_pirula_marron.jpg"
        filename = f"reporte_dia_hora_{timezone.now().strftime('%Y%m%d')}.pdf"
        response = render_to_pdf("reportes/pdf/dia_hora_pdf.html", context)
        if response.status_code == 200:
            response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response

    # ------------------ LÓGICA PRINCIPAL ------------------
    def _get_datos_base(self, request):
        ventas_view = ReporteVentasView()
        (ventas_qs,desde,hasta,medio_seleccionado,categoria_id,negocio,dia_ref,) = ventas_view._get_ventas_filtradas(request)

        # Hoy real de sistema (para proteger por backend)
        hoy_sistema = timezone.now().date()

        # Protección extra por si cambian algo en el DOM
        if desde > hoy_sistema:
            desde = hoy_sistema
        if hasta > hoy_sistema:
            hasta = hoy_sistema
        if hasta < desde:
            hasta = desde

        # Sólo ventas cerradas
        ventas_qs = ventas_qs.filter(estado=Venta.EST_CERRADA)

        # Solo ventas cerradas
        ventas_qs = ventas_qs.filter(estado=Venta.EST_CERRADA)

        # Si no hay ventas lleva a una estructura vacia
        if not ventas_qs.exists():
            return {
                "ventas_qs": ventas_qs,
                "desde": desde,
                "hasta": hasta,
                "hoy": dia_ref,          # fecha de referencia del filtro
                "hoy_sistema": hoy_sistema,
                "total_pedidos": 0,
                "total_monto": 0,
                "ventas_por_hora": [],
                "ventas_por_dia": [],
                "dia_hora_list": [],
                "top3": [],
                "bottom3": [],
                "chart_horas_labels_json": "[]",
                "chart_horas_data_json": "[]",
                "chart_dias_labels_json": "[]",
                "chart_dias_data_json": "[]",
            }

        # Totales
        total_pedidos = ventas_qs.values("id").distinct().count()
        total_monto = (
            ventas_qs.annotate(
                total_venta=F("items__cantidad") * F("items__precio_unit")
            )
            .aggregate(total=Sum("total_venta"))["total"]
            or 0
        )

        # -------- Distribución por HORA ----------
        ventas_por_hora_qs = (
            ventas_qs.annotate(hora=ExtractHour("fecha"))
            .values("hora")
            .annotate(
                cantidad=Count("id", distinct=True),
                total=Sum(F("items__cantidad") * F("items__precio_unit")),
            )
            .order_by("hora")
        )
        ventas_por_hora = list(ventas_por_hora_qs)

        horas_labels = [f"{h:02d}:00" for h in range(24)]
        cantidad_por_hora = {row["hora"]: row["cantidad"]
                             for row in ventas_por_hora}
        chart_horas_data = [cantidad_por_hora.get(h, 0) for h in range(24)]

        # -------- Distribución por DÍA ----------
        ventas_por_dia_qs = (
            ventas_qs.annotate(dia_semana=ExtractWeekDay("fecha"))
            .values("dia_semana")
            .annotate(
                cantidad=Count("id", distinct=True),
                total=Sum(F("items__cantidad") * F("items__precio_unit")),
            )
        )
        ventas_por_dia = list(ventas_por_dia_qs)

        orden_dias = [2, 3, 4, 5, 6, 7, 1]  # Lunes–Domingo
        cantidad_por_dia = {row["dia_semana"]: row["cantidad"]
                            for row in ventas_por_dia}
        chart_dias_labels = [self.DIA_SEMANA_LABELS[d] for d in orden_dias]
        chart_dias_data = [cantidad_por_dia.get(d, 0) for d in orden_dias]

        # --------  Combinación DÍA + HORA ----------
        dia_hora_qs = (
            ventas_qs.annotate(
                dia_semana=ExtractWeekDay("fecha"),
                hora=ExtractHour("fecha"),
            )
            .values("dia_semana", "hora")
            .annotate(
                cantidad=Count("id", distinct=True),
                total=Sum(F("items__cantidad") * F("items__precio_unit")),
            )
            .order_by("dia_semana", "hora")
        )

        dia_hora_list = [
            {
                "dia_semana": row["dia_semana"],
                "dia_label": self.DIA_SEMANA_LABELS.get(row["dia_semana"], "-"),
                "hora": row["hora"],
                "hora_label": f"{row['hora']:02d}:00",
                "cantidad": row["cantidad"],
                "total": row["total"] or 0,
            }
            for row in dia_hora_qs
        ]

        # Top / bottom 3
        top3 = sorted(dia_hora_list, key=lambda r: r["cantidad"], reverse=True)[:3]
        bottom3 = sorted(dia_hora_list, key=lambda r: r["cantidad"])[:3]

        ventas_por_dia = []
        chart_dias_labels = []
        chart_dias_data = []

        return {
            "ventas_qs": ventas_qs,
            "desde": desde,
            "hasta": hasta,
            "hoy": dia_ref,
            "hoy_sistema": hoy_sistema,
            "total_pedidos": total_pedidos,
            "total_monto": total_monto,
            "ventas_por_hora": ventas_por_hora,
            "ventas_por_dia": ventas_por_dia,
            "dia_hora_list": dia_hora_list,
            "top3": top3,
            "bottom3": bottom3,
            "chart_horas_labels_json": json.dumps(horas_labels),
            "chart_horas_data_json": json.dumps(chart_horas_data),
            "chart_dias_labels_json": json.dumps(chart_dias_labels),
            "chart_dias_data_json": json.dumps(chart_dias_data),
        }

    # ------------------ CONTEXTO ------------------
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        datos = self._get_datos_base(self.request)

        desde = datos["desde"]
        hasta = datos["hasta"]
        hoy_sistema = datos["hoy_sistema"]

        context.update(
            {
                "desde": desde,
                "hasta": hasta,
                "desde_str": desde.strftime("%Y-%m-%d") if desde else "",
                "hasta_str": hasta.strftime("%Y-%m-%d") if hasta else "",
                "hoy_sistema": hoy_sistema,
                "total_pedidos": datos["total_pedidos"],
                "total_monto": datos["total_monto"],
                "ventas_por_hora": datos["ventas_por_hora"],
                "ventas_por_dia": datos["ventas_por_dia"],
                "dia_hora_list": datos["dia_hora_list"],
                "top3": datos["top3"],
                "bottom3": datos["bottom3"],
                "chart_horas_labels_json": datos["chart_horas_labels_json"],
                "chart_horas_data_json": datos["chart_horas_data_json"],
                "chart_dias_labels_json": datos["chart_dias_labels_json"],
                "chart_dias_data_json": datos["chart_dias_data_json"],
            }
        )
        return context

    # ------------------ EXPORT CSV ------------------
    def export_csv(self, request):
        datos = self._get_datos_base(request)
        dia_hora_list = datos["dia_hora_list"]

        response = HttpResponse(content_type="text/csv")
        filename = f"reporte_dia_hora_{datos['desde']}_a_{datos['hasta']}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        response.write("\ufeff".encode("utf-8"))

        writer = csv.writer(response, delimiter=';')

        writer.writerow(["Día de la semana", "Hora",
                        "Cantidad de pedidos", "Monto total"])

        for row in dia_hora_list:
            writer.writerow([
                row["dia_label"],
                row["hora_label"],
                row["cantidad"],
                row["total"],
            ])

        return response

