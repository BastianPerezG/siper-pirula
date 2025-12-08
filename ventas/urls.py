from django.urls import path
from .views import VentaListaView, VentaDetalleView, VentaEnEsperaListaView, CajaTurnoListaView, CajaTurnoDetalleView
from . import views
app_name = "ventas"

urlpatterns = [
    path("", VentaListaView.as_view(), name="venta_lista"),
    path("nueva/", views.venta_crear_view, name="venta_crear"),
    path("<int:pk>/", VentaDetalleView.as_view(), name="venta_detalle"),
    # Ventas en espera
    path("en-espera/", VentaEnEsperaListaView.as_view(), name="ventas_en_espera_lista"),
    path("<int:pk>/cobrar/", views.venta_cobrar_view, name="venta_cobrar"),
    path("<int:pk>/editar/", views.venta_editar_view, name="venta_editar"),
    # Anulación
    path("<int:pk>/anular/", views.venta_anular_view, name="venta_anular"),

    # --- Caja / Arqueos --- #
    path("caja/historial/", CajaTurnoListaView.as_view(), name="caja_historial"),
    path("caja/<int:pk>/detalle/", CajaTurnoDetalleView.as_view(), name="caja_detalle"),
    path("caja/apertura/", views.caja_apertura_view, name="caja_apertura"),
    path("caja/arqueo/", views.caja_arqueo_parcial_view, name="caja_arqueo_parcial"),
    path("caja/cierre/", views.caja_cierre_view, name="caja_cierre"),
    path("caja/<int:pk>/pdf/", views.caja_pdf_view, name="caja_pdf"),

]