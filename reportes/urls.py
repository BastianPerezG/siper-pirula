from django.urls import path
from . import views

app_name = "reportes"

urlpatterns = [
    path("", views.ReporteComprasView.as_view(), name="index"),
    path("inventario/", views.ReporteInventarioView.as_view(), name="inventario"),
    path("ventas/", views.ReporteVentasView.as_view(), name="ventas"),
    path("compras/", views.ReporteComprasView.as_view(), name="compras"),
    path("dia-hora/", views.ReporteDiaHoraView.as_view(), name="dia-hora"),
    path("no-retira/", views.ReporteNoRetiraView.as_view(), name="no-retira"),
    path("ventas/", views.ReporteVentasView.as_view(), name="ventas"),
    path("no-retira/", views.ReporteNoRetiraView.as_view(), name="no-retira"),
    path("mermas-proveedor/",views.ReporteMermasProveedorView.as_view(),name="mermas-proveedor"),

]
