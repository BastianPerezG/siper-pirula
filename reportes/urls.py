from django.urls import path
from . import views

app_name = "reportes"

urlpatterns = [
    path("ventas/", views.ReporteVentasView.as_view(), name="ventas"),
    path("dia-hora/", views.ReporteDiaHoraView.as_view(), name="dia-hora"),
    path("no-retira/", views.ReporteNoRetiraView.as_view(), name="no-retira"),
    path("mermas-proveedor/", views.ReporteMermasProveedorView.as_view(),name="mermas-proveedor"),
    path("quiebres/", views.ReporteStockQuiebresView.as_view(), name="reporte_quiebres"),



    

]
