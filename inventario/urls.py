from django.urls import path
from . import views

app_name = "inventario"

urlpatterns = [
    path("scan/", views.scan_ean, name="scan_ean"),
    # Productos
    path("productos/", views.ProductoListaView.as_view(), name="producto_lista"),
    path("producto/crear/", views.ProductoCrearView.as_view(), name="producto_crear"),
    path("producto/<int:pk>/", views.ProductoDetalleView.as_view(), name="producto_detalle"),
    path("producto/<int:pk>/editar/", views.ProductoActualizarView.as_view(), name="producto_editar"),
    path("productos/<int:pk>/toggle-activo/", views.producto_toggle_activo, name="producto_toggle_activo",
),
    # Movimientos de stock
    path("flujos/", views.FlujosInventarioView.as_view(), name="flujos_inventario"),
    path("producto/<int:producto_pk>/movimiento/crear/", views.MovimientoCrearView.as_view(), name="movimiento_crear"),
    path("producto/<int:producto_pk>/movimientos/", views.MovimientoListaView.as_view(), name="movimiento_lista"),
    path("productos/stock-critico/", views.ProductoStockCriticoView.as_view(), name="producto_stock_critico"),
    # Compras
    path("compras/", views.CompraListaView.as_view(), name="compra_lista"),
    path("compras/nueva/", views.compra_crear_view, name="compra_crear"),
    path("compras/<int:pk>/editar/", views.compra_editar_view, name="compra_editar"),
    path("compras/<int:pk>/", views.CompraDetalleView.as_view(), name="compra_detalle"),
    path("compras/<int:pk>/eliminar/", views.CompraEliminarView.as_view(), name="compra_eliminar"),
    # Proveedores
    path("proveedores/", views.ProveedorListView.as_view(), name="proveedor_lista"),
    path("proveedores/crear/", views.ProveedorCreateView.as_view(), name="proveedor_crear"),
    path("proveedores/<int:pk>/editar/", views.ProveedorUpdateView.as_view(), name="proveedor_actualizar"),
    path("proveedores/<int:pk>/ocultar/", views.ProveedorToggleActivoView.as_view(), name="proveedor_ocultar"),
    path("proveedores/<int:pk>/plantilla/", views.ProveedorPlantillaView.as_view(), name="proveedor_plantilla"),
    path("proveedores/<int:pk>/plantilla/pdf/", views.proveedor_plantilla_pdf_view, name="proveedor_plantilla_pdf"),
    # Plantillas proveedor-producto
    path("plantilla/<int:proveedor_id>/plantilla", views.PlantillaProveedorProductoListView.as_view(), name="plantilla_lista"),
    path("plantilla/<int:pk>/detalle", views.ProveedorDetailView.as_view(), name="proveedor_detalle"),
    # Categorías
    path("categorias/", views.CategoriaListaView.as_view(), name="categoria_lista"),
    path("categorias/nueva/", views.CategoriaCrearView.as_view(), name="categoria_crear"),
    path("categorias/<int:pk>/editar/", views.CategoriaActualizarView.as_view(), name="categoria_editar"),
    path("categorias/<int:pk>/toggle/", views.CategoriaToggleActivaView.as_view(), name="categoria_toggle_activa"),
    # Marcas
    path("marcas/", views.MarcaListaView.as_view(), name="marca_lista"),
    path("marcas/nueva/", views.MarcaCrearView.as_view(), name="marca_crear"),
    path("marcas/<int:pk>/editar/", views.MarcaActualizarView.as_view(), name="marca_editar"),
    path("marcas/<int:pk>/toggle/", views.MarcaToggleActivaView.as_view(), name="marca_toggle_activa"),
    # Promociones
    path("promos/", views.promo_lista_view, name="promo_lista"),
    path("promos/<int:pk>/", views.promo_detalle_view, name="promo_detalle"),
    path("promos/nueva/", views.promo_crear_view, name="promo_crear"),
    path("promos/<int:pk>/editar/", views.promo_editar_view, name="promo_editar"),
    path("promos/<int:pk>/toggle/", views.promo_toggle_activa_view, name="promo_toggle"),
    # Mermas
    path("mermas/", views.merma_lista, name="merma_lista"),
    path("mermas/nueva/", views.merma_crear, name="merma_crear"),
    path("mermas/<int:pk>/editar/", views.merma_editar, name="merma_editar"),
    path("mermas/<int:pk>/eliminar/", views.merma_eliminar, name="merma_eliminar"),
    # API
    path("api/sugerencias/", views.sugerencias_productos, name="sugerencias_productos"),
    path("api/producto/<int:pk>/", views.api_producto_detalle, name="api_producto_detalle"),
]
