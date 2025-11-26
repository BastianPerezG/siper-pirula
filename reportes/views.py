
# reportes/views.py
import csv
import json
from django.db.models.functions import TruncDay
from datetime import datetime
from django.http import HttpResponse
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.db.models import Sum, F, Count
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth, TruncYear, ExtractYear, ExtractYear,ExtractHour,ExtractWeekDay
from django.db.models import DecimalField
from inventario.models import Compra, CompraItem, Categoria, Producto, Proveedor
from ventas.models import Venta, VentaItem



class ReporteInventarioView(LoginRequiredMixin, TemplateView):
    template_name = "reportes/inventario.html"

    def _get_ventas_filtradas(self, request):
        negocio = request.user.perfilusuario.negocio
        hoy = timezone.now().date()

        # Filtros desde la URL (?desde=YYYY-MM-DD&hasta=YYYY-MM-DD...)
        desde_str = request.GET.get("desde")
        hasta_str = request.GET.get("hasta")
        medio = request.GET.get("medio") or None
        categoria_id = request.GET.get("categoria") or None

        # Si no hay fechas, usamos el mes actual
        if not desde_str or not hasta_str:
            desde = hoy.replace(day=1)
            hasta = hoy
        else:
            # los <input type="date"> envían el formato YYYY-MM-DD
            desde = datetime.strptime(desde_str, "%Y-%m-%d").date()
            hasta = datetime.strptime(hasta_str, "%Y-%m-%d").date()

        ventas_qs = Venta.objects.filter(
            negocio=negocio,
            estado=Venta.EST_CERRADA,
            fecha__date__gte=desde,
            fecha__date__lte=hasta,
        )

        if medio:
            ventas_qs = ventas_qs.filter(medio_pago=medio)

        if categoria_id:
            ventas_qs = ventas_qs.filter(
                items__producto__categoria_id=categoria_id)

        return ventas_qs.distinct(), desde, hasta, medio, categoria_id, hoy, negocio

    # ---------- GET: si viene ?export=csv, descargamos ----------
    def get(self, request, *args, **kwargs):
        ventas_qs, _, _, _, _, _, _ = self._get_ventas_filtradas(request)

        if request.GET.get("export") == "csv":
            return self.export_csv(ventas_qs)

        # si no es export, seguimos con el flujo normal (HTML)
        return super().get(request, *args, **kwargs)

    # ---------- EXPORTACIÓN A CSV ----------
    def export_csv(self, ventas_qs):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="reporte_ventas_{timezone.now().date()}.csv"'
        )

        writer = csv.writer(response)
        writer.writerow(["Fecha", "Medio de pago", "Total"])

        for v in ventas_qs.select_related():
            writer.writerow([
                v.fecha.date(),
                v.get_medio_pago_display(),
                v.total,
            ])

        return response

    # ---------- CONTEXTO PARA EL TEMPLATE ----------
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request = self.request

        ventas_qs, desde, hasta, medio, categoria_id, hoy, negocio = self._get_ventas_filtradas(
            request)

        # --- resumen rango filtrado ---
        total_rango = ventas_qs.aggregate(
            total=Sum(F("items__cantidad") * F("items__precio_unit"))
        )["total"] or 0
        cantidad_ventas_rango = ventas_qs.count()
        ticket_promedio_rango = (
            total_rango / cantidad_ventas_rango if cantidad_ventas_rango else 0
        )

        # --- agrupaciones día / semana / mes ---
        ventas_por_dia = (
            ventas_qs
            .annotate(dia=TruncDay("fecha"))
            .values("dia")
            .annotate(
                total=Sum(F("items__cantidad") * F("items__precio_unit")),
                pedidos=Count("id", distinct=True),
            )
            .order_by("dia")
        )

        ventas_por_semana = (
            ventas_qs
            .annotate(semana=TruncWeek("fecha"))
            .values("semana")
            .annotate(
                total=Sum(F("items__cantidad") * F("items__precio_unit")),
                pedidos=Count("id", distinct=True),
            )
            .order_by("semana")
        )

        ventas_por_mes = (
            ventas_qs
            .annotate(mes=TruncMonth("fecha"))
            .values("mes")
            .annotate(
                total=Sum(F("items__cantidad") * F("items__precio_unit")),
                pedidos=Count("id", distinct=True),
            )
            .order_by("mes")
        )

        def ticket_promedio(lista):
            total = sum((fila["total"] or 0) for fila in lista)
            pedidos = sum((fila["pedidos"] or 0) for fila in lista)
            return int(total / pedidos) if pedidos else 0

        ticket_dia = ticket_promedio(ventas_por_dia)
        ticket_semana = ticket_promedio(ventas_por_semana)
        ticket_mes = ticket_promedio(ventas_por_mes)

        # --- ventas hoy y del mes actual (para las tarjetas) ---
        ventas_hoy = Venta.objects.filter(
            negocio=negocio,
            estado=Venta.EST_CERRADA,
            fecha__date=hoy,
        )
        total_hoy = sum(v.total for v in ventas_hoy)

        ventas_mes_actual = Venta.objects.filter(
            negocio=negocio,
            estado=Venta.EST_CERRADA,
            fecha__year=hoy.year,
            fecha__month=hoy.month,
        )
        total_mes_actual = sum(v.total for v in ventas_mes_actual)
        cant_ventas_mes_actual = ventas_mes_actual.count()
        ticket_promedio_mes_actual = (
            total_mes_actual / cant_ventas_mes_actual if cant_ventas_mes_actual else 0
        )

        # --- ventas por medio de pago y top productos ---
        ventas_por_medio = (
            ventas_qs
            .values("medio_pago")
            .annotate(
                total=Sum(F("items__cantidad") * F("items__precio_unit")),
                cantidad=Count("id", distinct=True),
            )
            .order_by("medio_pago")
        )

        top_productos = (
            VentaItem.objects
            .filter(venta__in=ventas_qs)
            .values("producto__nombre", "producto__categoria__nombre")
            .annotate(
                unidades=Sum("cantidad"),
                total=Sum(F("cantidad") * F("precio_unit")),
            )
            .order_by("-unidades")[:10]
        )

        # --- contexto final ---
        context.update({
            "desde": desde,
            "hasta": hasta,
            "medio_seleccionado": medio,
            "categoria_seleccionada": int(categoria_id) if categoria_id else None,
            "medios_pago": Venta.MEDIO_PAGO_CHOICES,
            "categorias": Categoria.objects.filter(negocio=negocio),

            "total_rango": total_rango,
            "cantidad_ventas_rango": cantidad_ventas_rango,
            "ticket_promedio_rango": ticket_promedio_rango,

            "ventas_por_dia": ventas_por_dia,
            "ventas_por_semana": ventas_por_semana,
            "ventas_por_mes": ventas_por_mes,
            "ticket_dia": ticket_dia,
            "ticket_semana": ticket_semana,
            "ticket_mes": ticket_mes,

            "ventas_hoy": ventas_hoy,
            "total_hoy": total_hoy,
            "ventas_mes": ventas_mes_actual,
            "total_mes": total_mes_actual,
            "ticket_promedio_mes": ticket_promedio_mes_actual,

            "pagos": ventas_por_medio,
            "top_productos": top_productos,
            "hoy": hoy,
        })
        return context

    template_name = "reportes/ventas.html"

    # ----------------- Filtros compartidos (formulario + CSV + gráfico) -----------------
    def _get_ventas_filtradas(self, request):
        negocio = request.user.perfilusuario.negocio
        hoy = timezone.now().date()

        ventas = Venta.objects.filter(
            negocio=negocio,
            estado=Venta.EST_CERRADA,
        )

        # Filtros GET
        desde_str = request.GET.get("desde")
        hasta_str = request.GET.get("hasta")
        medio = request.GET.get("medio") or ""
        categoria_id = request.GET.get("categoria") or ""

        # Si no envían fechas, usamos el mes actual
        if desde_str:
            try:
                desde = datetime.strptime(desde_str, "%Y-%m-%d").date()
            except ValueError:
                desde = hoy.replace(day=1)
        else:
            desde = hoy.replace(day=1)

        if hasta_str:
            try:
                hasta = datetime.strptime(hasta_str, "%Y-%m-%d").date()
            except ValueError:
                hasta = hoy
        else:
            hasta = hoy

        ventas = ventas.filter(fecha__date__gte=desde, fecha__date__lte=hasta)

        if medio:
            ventas = ventas.filter(medio_pago=medio)

        if categoria_id:
            # Filtramos por categoría a través de VentaItem
            venta_ids = (
                VentaItem.objects
                .filter(producto__categoria_id=categoria_id)
                .values_list("venta_id", flat=True)
            )
            ventas = ventas.filter(id__in=venta_ids)

        return ventas.distinct(), desde, hasta, medio, categoria_id, negocio, hoy

    # ----------------- GET: CSV o HTML -----------------
    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv":
            ventas_qs, *_ = self._get_ventas_filtradas(request)
            return self.export_csv(ventas_qs)
        return super().get(request, *args, **kwargs)

    # ----------------- Exportar CSV -----------------
    def export_csv(self, ventas_qs):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="reporte_ventas_{timezone.now().date()}.csv"'
        )

        # BOM para que Excel reconozca bien UTF-8
        response.write("\ufeff")

        writer = csv.writer(response, delimiter=";")
        writer.writerow(["Fecha", "Medio de pago", "Total"])

        for v in ventas_qs.select_related():
            writer.writerow([
                v.fecha.date() if hasattr(v.fecha, "date") else v.fecha,
                v.get_medio_pago_display(),
                v.total,  # si no tienes campo total, cámbialo por una agregación
            ])

        return response

    # ----------------- Contexto para el dashboard -----------------
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request = self.request

        ventas_filtradas, desde, hasta, medio, categoria_id, negocio, hoy = \
            self._get_ventas_filtradas(request)

        # ==== Tarjetas: ventas hoy y ventas del mes actual ====
        ventas_hoy = Venta.objects.filter(
            negocio=negocio,
            estado=Venta.EST_CERRADA,
            fecha__date=hoy,
        )
        total_hoy = sum(v.total for v in ventas_hoy)

        ventas_mes = Venta.objects.filter(
            negocio=negocio,
            estado=Venta.EST_CERRADA,
            fecha__year=hoy.year,
            fecha__month=hoy.month,
        )
        total_mes = sum(v.total for v in ventas_mes)
        cant_ventas_mes = ventas_mes.count()
        ticket_promedio_mes = total_mes / cant_ventas_mes if cant_ventas_mes else 0

        # ==== Tabla: total por medio de pago (mes actual) ====
        pagos = (
            VentaItem.objects
            .filter(venta__in=ventas_mes)
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

        # ==== Top productos más vendidos (mes actual) ====
        top_productos = (
            VentaItem.objects
            .filter(venta__in=ventas_mes)
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

        # =====================================================
        #   GRÁFICO ÚNICO (Día / Mes / Año) – respeta filtros
        # =====================================================
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

        # =====================================================
        #   KPIs Año vs Año (ventas totales del año completo)
        # =====================================================
        anio_actual = hoy.year
        anio_anterior = hoy.year - 1

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
            "medios_pago": Venta.MEDIO_PAGO_CHOICES,
            "categorias": Categoria.objects.filter(negocio=negocio),

            # Tarjetas
            "ventas_hoy": ventas_hoy,
            "total_hoy": total_hoy,
            "ventas_mes": ventas_mes,
            "total_mes": total_mes,
            "ticket_promedio_mes": ticket_promedio_mes,

            # Tablas
            "pagos": pagos,
            "top_productos": top_productos,

            "hoy": hoy,

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


class ReporteVentasView(LoginRequiredMixin, TemplateView):
    template_name = "reportes/ventas.html"


    def _get_ventas_filtradas(self, request):
        negocio = request.user.perfilusuario.negocio
        hoy = timezone.now().date()

        ventas = Venta.objects.filter(
            negocio=negocio,
            estado=Venta.EST_CERRADA,
        )

        desde_str = request.GET.get("desde")
        hasta_str = request.GET.get("hasta")
        medio = request.GET.get("medio") or ""
        categoria_id = request.GET.get("categoria") or ""

        # Si no envían fechas, usamos el mes actual
        if desde_str:
            try:
                desde = datetime.strptime(desde_str, "%Y-%m-%d").date()
            except ValueError:
                desde = hoy.replace(day=1)
        else:
            desde = hoy.replace(day=1)

        if hasta_str:
            try:
                hasta = datetime.strptime(hasta_str, "%Y-%m-%d").date()
            except ValueError:
                hasta = hoy
        else:
            hasta = hoy

        ventas = ventas.filter(fecha__date__gte=desde, fecha__date__lte=hasta)

        if medio:
            ventas = ventas.filter(medio_pago=medio)

        if categoria_id:
            # Filtramos por categoría a través de VentaItem
            venta_ids = (
                VentaItem.objects
                .filter(producto__categoria_id=categoria_id)
                .values_list("venta_id", flat=True)
            )
            ventas = ventas.filter(id__in=venta_ids)

        return ventas.distinct(), desde, hasta, medio, categoria_id, negocio, hoy

    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv":
            ventas_qs, *_ = self._get_ventas_filtradas(request)
            return self.export_csv(ventas_qs)
        return super().get(request, *args, **kwargs)

    # ----------------- Exportar CSV -----------------
    def export_csv(self, ventas_qs):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="reporte_ventas_{timezone.now().date()}.csv"'
        )

        response.write("\ufeff")

        writer = csv.writer(response, delimiter=";")
        writer.writerow(["Fecha", "Medio de pago", "Total"])

        for v in ventas_qs.select_related():
            writer.writerow([
                v.fecha.date() if hasattr(v.fecha, "date") else v.fecha,
                v.get_medio_pago_display(),
                v.total,
            ])

        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request = self.request

        ventas_filtradas, desde, hasta, medio, categoria_id, negocio, hoy = \
            self._get_ventas_filtradas(request)

        ventas_hoy = Venta.objects.filter(
            negocio=negocio,
            estado=Venta.EST_CERRADA,
            fecha__date=hoy,
        )
        total_hoy = sum(v.total for v in ventas_hoy)

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

        # =====================================================
        #   GRÁFICO ÚNICO (Día / Mes / Año) – respeta filtros
        # =====================================================
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

        # =====================================================
        #   KPIs Año vs Año (ventas totales del año completo)
        # =====================================================
        anio_actual = hoy.year
        anio_anterior = hoy.year - 1

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
            "medios_pago": Venta.MEDIO_PAGO_CHOICES,
            "categorias": Categoria.objects.filter(negocio=negocio),

            # Tarjetas
            "ventas_hoy": ventas_hoy,
            "total_hoy": total_hoy,
            "ventas_mes": ventas_filtradas,          # ahora es el período filtrado
            "total_mes": total_periodo,
            "ticket_promedio_mes": ticket_promedio_periodo,

            # Tablas
            "pagos": pagos,
            "top_productos": top_productos,

            "hoy": hoy,

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


class ReporteComprasView(LoginRequiredMixin, TemplateView):
    """
    Reporte de compras:
    - Total de compras del mes
    - Total por proveedor
    - Productos más comprados
    """
    template_name = "reportes/compras.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        negocio = self.request.user.perfilusuario.negocio
        hoy = timezone.now().date()

        compras_qs = Compra.objects.filter(negocio=negocio)

        # Compras del mes
        compras_mes = compras_qs.filter(
            fecha__year=hoy.year,
            fecha__month=hoy.month,
        )

        # Total del mes (sumando cantidad * costo_unit)
        total_mes = (
            CompraItem.objects
            .filter(compra__in=compras_mes)
            .aggregate(
                total=Sum(F("cantidad") * F("costo_unit"))
            )["total"] or 0
        )

        # Total por proveedor
        compras_por_proveedor = (
            CompraItem.objects
            .filter(compra__negocio=negocio)
            .values("compra__proveedor__nombre")
            .annotate(
                total=Sum(F("cantidad") * F("costo_unit")),
            )
            .order_by("-total")
        )

        # Top 10 productos más comprados
        top_comprados = (
            CompraItem.objects
            .filter(compra__negocio=negocio)
            .values("producto__nombre")
            .annotate(
                unidades=Sum("cantidad"),
                total=Sum(F("cantidad") * F("costo_unit")),
            )
            .order_by("-unidades")[:10]
        )

        context.update({
            "compras_mes": compras_mes,
            "total_mes": total_mes,
            "compras_por_proveedor": compras_por_proveedor,
            "top_comprados": top_comprados,
            "hoy": hoy,
        })
        return context


    template_name = "reportes/stock.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        negocio = self.request.user.perfilusuario.negocio

        # ======= Productos críticos =======
        productos_criticos = Producto.objects.filter(
            movimientos__stock_actual__lte=F("stock_min"),
            movimientos__stock_actual__gt=0,
            negocio=negocio
        )

        # ======= Productos en quiebre =======
        productos_quiebre = Producto.objects.filter(
            movimientos__stock_actual__lte=0,
            negocio=negocio
)

        # ======= Historial de quiebres filtrado por fechas =======
        desde = self.request.GET.get("desde")
        hasta = self.request.GET.get("hasta")

        historial = HistorialQuiebres.objects.all()

        if desde:
            historial = historial.filter(fecha_quiebre__date__gte=desde)
        if hasta:
            historial = historial.filter(fecha_quiebre__date__lte=hasta)

        context.update({
            "productos_criticos": productos_criticos,
            "productos_quiebre": productos_quiebre,
            "historial": historial,
            "desde": desde,
            "hasta": hasta,
        })

        return context


    template_name = "reportes/stock.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        productos = Producto.objects.all()


        # Filtros
        categoria_id = self.request.GET.get("categoria")
        proveedor = self.request.GET.get("proveedor")
        estado = self.request.GET.get("estado")  # critico | quiebre | ambos

        productos = Producto.objects.all()

        if categoria_id:
            productos = productos.filter(categoria_id=categoria_id)

        # ========== CALCULAR STOCK ==========
        productos_con_datos = []
        for p in productos:
            movimientos = MovimientoStock.objects.filter(producto=p)
            stock_actual = sum(m.cantidad for m in movimientos)

            productos_con_datos.append({
                "producto": p,
                "stock_actual": stock_actual,
                "stock_min": p.stock_min,
                "diferencia": p.stock_min - stock_actual,
                "proveedor": p.ubicacion,  # o tu campo proveedor real si lo tienes
                "en_quiebre": stock_actual <= 0,
                "critico": 0 < stock_actual <= p.stock_min,
            })

        # ========== FILTRAR SEGÚN ESTADO ==========
        if estado == "critico":
            productos_con_datos = [
                p for p in productos_con_datos if p["critico"]]
        elif estado == "quiebre":
            productos_con_datos = [
                p for p in productos_con_datos if p["en_quiebre"]]

        productos_con_datos.sort(key=lambda x: x["stock_actual"])

        context["productos"] = productos_con_datos

        return context


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
        if request.GET.get("export") == "csv":
            return self.export_csv(request)
        return super().get(request, *args, **kwargs)

    def _get_datos_base(self, request):
       
        # Reutilizamos el método ya existente en ReporteVentasView
        ventas_view = ReporteVentasView()
        (ventas_qs,desde,hasta,medio_seleccionado,categoria_id,hoy,negocio,) = ventas_view._get_ventas_filtradas(request)

        # Si no hay ventas en el rango, devolvemos todo vacío pero sin romper nada
        if not ventas_qs.exists():
            return {
                "ventas_qs": ventas_qs,
                "desde": desde,
                "hasta": hasta,
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

        # Total de pedidos y monto total del período
        total_pedidos = ventas_qs.values("id").distinct().count()
        total_monto = (
            ventas_qs.annotate(
                total_venta=F("items__cantidad") * F("items__precio_unit")
            )
            .aggregate(total=Sum("total_venta"))["total"]
            or 0
        )

        # --- Distribución por HORA (0–23) ---
        ventas_por_hora_qs = (
            ventas_qs.annotate(hora = ExtractHour("fecha"))
            .values("hora")
            .annotate(
                cantidad=Count("id", distinct=True),
                total=Sum(F("items__cantidad") * F("items__precio_unit")),
            )
            .order_by("hora")
        )

        ventas_por_hora = list(ventas_por_hora_qs)

        # Para el gráfico: rellenamos todas las horas aunque no haya datos
        horas_labels = [f"{h:02d}:00" for h in range(24)]
        cantidad_por_hora = {row["hora"]: row["cantidad"]
                             for row in ventas_por_hora}
        chart_horas_data = [cantidad_por_hora.get(h, 0) for h in range(24)]

        # --- Distribución por DÍA DE LA SEMANA ---
        ventas_por_dia_qs = (
            ventas_qs.annotate(dia_semana = ExtractWeekDay("fecha"))
            .values("dia_semana")
            .annotate(
                cantidad=Count("id", distinct=True),
                total=Sum(F("items__cantidad") * F("items__precio_unit")),
            )
        )

        ventas_por_dia = list(ventas_por_dia_qs)

        # Ordenamos Lunes–Domingo (en ExtractWeekDay 1=Domingo)
        orden_dias = [2, 3, 4, 5, 6, 7, 1]
        cantidad_por_dia = {
            row["dia_semana"]: row["cantidad"] for row in ventas_por_dia
        }
        chart_dias_labels = [self.DIA_SEMANA_LABELS[d] for d in orden_dias]
        chart_dias_data = [cantidad_por_dia.get(d, 0) for d in orden_dias]

        # --- Combinación DÍA + HORA ---
        dia_hora_qs = (
            ventas_qs.annotate(
                dia_semana = ExtractWeekDay("fecha"),
                hora = ExtractHour("fecha"),
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
                "total": row["total"],
            }
            for row in dia_hora_qs
        ]

        # Top 3 y Bottom 3 por cantidad de pedidos
        top3 = sorted(
            dia_hora_list, key=lambda r: r["cantidad"], reverse=True)[:3]
        bottom3 = sorted(dia_hora_list, key=lambda r: r["cantidad"])[:3]

        import json

        return {
            "ventas_qs": ventas_qs,
            "desde": desde,
            "hasta": hasta,
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        datos = self._get_datos_base(self.request)

        context.update(
            {
                "desde": datos["desde"],
                "hasta": datos["hasta"],
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

    def export_csv(self, request):
        """
        Exporta la tabla día x hora a CSV para usarla en Excel.
        """
        datos = self._get_datos_base(request)
        dia_hora_list = datos["dia_hora_list"]

        response = HttpResponse(content_type="text/csv")
        filename = f"reporte_dia_hora_{datos['desde']}_a_{datos['hasta']}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        import csv

        writer = csv.writer(response)
        writer.writerow(
            ["Día de la semana", "Hora", "Cantidad de pedidos", "Monto total"]
        )

        for row in dia_hora_list:
            writer.writerow(
                [
                    row["dia_label"],
                    row["hora_label"],
                    row["cantidad"],
                    row["total"],
                ]
            )

        return response
