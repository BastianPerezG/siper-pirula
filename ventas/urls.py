from django.urls import path
from .views import VentaListaView, VentaDetalleView, venta_crear_view

app_name = "ventas"

urlpatterns = [
    path("", VentaListaView.as_view(), name="venta_lista"),
    path("nueva/", venta_crear_view, name="venta_crear"),
    path("<int:pk>/", VentaDetalleView.as_view(), name="venta_detalle"),
]
