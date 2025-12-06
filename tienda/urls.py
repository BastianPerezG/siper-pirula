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
    path("productos/", views.producto_lista, name="productos"),
    path("producto/<int:producto_id>/", views.producto_detalle, name="producto_detalle"),
    # carrito
    path("carrito/", views.carrito_ver, name="carrito_ver"),
    path("carrito/agregar/<int:producto_id>/", views.carrito_agregar, name="carrito_agregar"),
    path("carrito/actualizar/", views.carrito_actualizar, name="carrito_actualizar"),
    path("carrito/eliminar/<str:item_id>/", views.carrito_eliminar_view, name="carrito_eliminar"),
    path("carrito/vaciar/", views.carrito_vaciar, name="carrito_vaciar"),
    # checkout
    path("checkout/", views.checkout_view, name="checkout"),
    path("checkout/exito/<int:pedido_id>/", views.checkout_exito_view, name="checkout_exito"),

    # Login
    path("registro/", views.registro_cliente_view, name="registro"),
    path("login/", views.login_cliente_view, name="login"),
    path("logout/", views.logout_cliente_view, name="logout"),

    # Webpay
    path("webpay/retorno/", views.webpay_retorno_view, name="webpay_retorno"),
    
    #Carrito
     path("promo/<int:promo_id>/agregar/", views.promo_agregar_carrito_view, name="promo_agregar_carrito"),
]
