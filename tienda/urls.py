from django.urls import path
from . import views

app_name = "tienda"

urlpatterns = [
    path("", views.tienda_home, name="home"),
    path("ajax/sugerencias/", views.sugerencias_productos, name="sugerencias"),
    # categorías
    path(
        "categoria/<int:categoria_id>/",
        views.categoria_detalle,
        name="categoria_detalle",
    ),
    path("productos/", views.productos_list_view, name="productos"),
    path("producto/<int:producto_id>/", views.producto_detalle, name="producto_detalle"),
    path("promo/<int:promo_id>/", views.promo_detalle, name="promo_detalle"),
    # carrito
    path("carrito/", views.carrito_ver, name="carrito_ver"),
    path("carrito/agregar/<int:producto_id>/", views.carrito_agregar, name="carrito_agregar"),
    path("carrito/actualizar/", views.carrito_actualizar, name="carrito_actualizar"),
    path("carrito/actualizar-item/", views.carrito_actualizar_item, name="carrito_actualizar_item"),
    path("carrito/eliminar/<str:item_id>/", views.carrito_eliminar_view, name="carrito_eliminar"),
    path("carrito/vaciar/", views.carrito_vaciar, name="carrito_vaciar"),
    path("carrito/sincronizar/", views.carrito_sincronizar_localstorage, name="carrito_sincronizar"),
    path("carrito/obtener/", views.carrito_obtener_json, name="carrito_obtener"),
    # checkout
    path("checkout/", views.checkout_view, name="checkout"),
    path("checkout/exito/<int:pedido_id>/", views.checkout_exito_view, name="checkout_exito"),

    # Login
    path("registro/", views.registro_cliente_view, name="registro"),
    path("login/", views.login_cliente_view, name="login"),
    path("logout/", views.logout_cliente_view, name="logout"),
    path("perfil/", views.perfil_view, name="perfil"),
    path("perfil/editar/", views.perfil_editar_view, name="perfil_editar"),
    path("perfil/pedido/<int:pedido_id>/", views.pedido_detalle_view, name="pedido_detalle"),

    # Webpay
    path("webpay/retorno/", views.webpay_retorno_view, name="webpay_retorno"),
    
    #Carrito
     path("promo/<int:promo_id>/agregar/", views.promo_agregar_carrito_view, name="promo_agregar_carrito"),
    
    # Verificación de edad
    path("verificar-edad/", views.verificar_edad_view, name="verificar_edad"),
    path("terminos-y-condiciones/", views.terminos, name="terminos"),
]
