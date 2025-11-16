from django.urls import path
from . import views

app_name = "inventario"

urlpatterns = [
    path("scan/", views.scan_ean, name="scan_ean"),
    #URLS PARA PRODUCTOS
    path("productos/", views.ProductoListaView.as_view(), name="producto_lista"),
    path("producto/crear/", views.ProductoCrearView.as_view(), name="producto_crear"),
    path("producto/<int:pk>/", views.ProductoDetalleView.as_view(), name="producto_detalle"),
    path("producto/<int:pk>/editar/", views.ProductoActualizarView.as_view(), name="producto_editar"),
    #URL PARA FLUJO DE STOCK
    path("producto/<int:producto_pk>/movimiento/crear/",views.MovimientoCrearView.as_view(),name="movimiento_crear"),
    path("producto/<int:producto_pk>/movimientos/", views.MovimientoListaView.as_view(),name="movimiento_lista"),
    path("productos/stock-critico/", views.ProductoStockCriticoView.as_view(), name="producto_stock_critico"),
]