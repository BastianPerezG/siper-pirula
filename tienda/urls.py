from django.urls import path
from . import views

app_name = "tienda"

urlpatterns = [
    path("", views.tienda_home, name="home"),

    # categorías
    path(
        "categoria/<int:categoria_id>/",
        views.categoria_detalle,
        name="categoria_detalle",
    ),

    # carrito
    path("carrito/", views.carrito_ver, name="carrito_ver"),
    path("carrito/agregar/<int:producto_id>/", views.carrito_agregar, name="carrito_agregar"),
    path("carrito/eliminar/<int:producto_id>/", views.carrito_eliminar, name="carrito_eliminar"),
    path("carrito/actualizar/", views.carrito_actualizar, name="carrito_actualizar"),

    # checkout
    path("checkout/", views.checkout_view, name="checkout"),
    path("checkout/exito/<int:pedido_id>/", views.checkout_exito_view, name="checkout_exito"),
]