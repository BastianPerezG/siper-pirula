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
    # COMPRAS
    path("compras/", views.CompraListaView.as_view(), name="compra_lista"),
    path("compras/nueva/", views.compra_crear_view, name="compra_crear"),
    path("compras/<int:pk>/", views.CompraDetalleView.as_view(), name="compra_detalle"),
    path("compras/<int:pk>/eliminar/", views.CompraEliminarView.as_view(), name="compra_eliminar"),
    # Proveedores
    path("proveedores/", views.ProveedorListView.as_view(), name="proveedor_lista"),
    path("proveedores/crear/", views.ProveedorCreateView.as_view(), name="proveedor_crear"),
    path("proveedores/<int:pk>/editar/", views.ProveedorUpdateView.as_view(), name="proveedor_actualizar"),
    path("proveedores/<int:pk>/ocultar/", views.ProveedorHideView.as_view(), name="proveedor_ocultar"),
    # Plantilas P
    path("plantilla/<int:proveedor_id>/plantilla", views.PlantillaProveedorProductoListView.as_view(), name="plantilla_lista"),
    path("plantilla/<int:pk>/detalle", views.ProveedorDetailView.as_view(), name="proveedor_detalle"),

    
 
]