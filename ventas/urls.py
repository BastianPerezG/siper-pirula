from django.urls import path
from .views import (
    AuditoriaDescuentoListaView, 
    CodigoAutorizacionCreateView, 
    CodigoAutorizacionListaView, 
    CodigoAutorizacionUpdateView, 
    DescuentoReglaRolCreateView, 
    DescuentoReglaRolListaView, 
    DescuentoReglaRolToggleActivoView, 
    DescuentoReglaRolUpdateView, 
    VentaListaView, 
    VentaDetalleView, 
    VentaEnEsperaListaView, 
    CajaTurnoListaView, 
    CajaTurnoDetalleView,
    PagoPendienteListaView,
    )
from . import views

app_name = "ventas"

urlpatterns = [
    path("", VentaListaView.as_view(), name="venta_lista"),
    path("nueva/", views.venta_crear_view, name="venta_crear"),
    path("<int:pk>/", VentaDetalleView.as_view(), name="venta_detalle"),
    path("venta/<int:pk>/checkout/", views.venta_checkout_view, name="venta_checkout"),
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
    
    # --- Gestión Descuentos ---

    path("descuentos/reglas/",DescuentoReglaRolListaView.as_view(),name="descuento_reglas"),
    path("descuentos/reglas/nueva/",DescuentoReglaRolCreateView.as_view(),name="descuento_regla_crear"),
    path("descuentos/reglas/<int:pk>/editar/",DescuentoReglaRolUpdateView.as_view(),name="descuento_regla_editar"),
    path("descuentos/reglas/<int:pk>/toggle/",DescuentoReglaRolToggleActivoView.as_view(),name="descuento_regla_toggle"),

    # Códigos de autorización
    path("descuentos/codigos/",CodigoAutorizacionListaView.as_view(),name="codigo_descuento_lista"),
    path("descuentos/codigos/nuevo/", CodigoAutorizacionCreateView.as_view() ,name="codigo_descuento_crear"),
    path("descuentos/codigos/<int:pk>/editar/",CodigoAutorizacionUpdateView.as_view(),name="codigo_descuento_editar"),

    # Auditoría de descuentos
    path("descuentos/auditoria/",AuditoriaDescuentoListaView.as_view(),name="descuento_auditoria"),
    
    # --- Gestión de Pagos Pendientes ---
    path("pagos/pendientes/", views.PagoPendienteListaView.as_view(), name="pago_pendiente_lista"),
    path("pagos/<int:pk>/confirmar/", views.pago_confirmar_view, name="pago_confirmar"),
    
    # --- Datos bancarios y notas de venta ---
    path("<int:pk>/datos-bancarios/", views.venta_datos_bancarios_view, name="venta_datos_bancarios"),
    path("<int:pk>/nota-imprimir/", views.venta_nota_imprimir_view, name="venta_nota_imprimir"),
]