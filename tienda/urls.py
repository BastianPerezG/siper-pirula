from django.urls import path
from . import views

app_name = "tienda"

urlpatterns = [
    path("", views.tienda_home, name="home"),
    path("carrito/", views.carrito_ver, name="carrito_ver"),
    path("carrito/agregar/<int:producto_id>/", views.carrito_agregar, name="carrito_agregar"),
    path("carrito/actualizar/", views.carrito_actualizar, name="carrito_actualizar"),
    path("carrito/eliminar/<int:producto_id>/", views.carrito_eliminar, name="carrito_eliminar"),
    path("checkout/", views.checkout_view, name="checkout"),
    path("checkout/exito/<int:pedido_id>/", views.checkout_exito_view, name="checkout_exito"),
]
