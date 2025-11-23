from django.urls import path
from . import views

app_name = "pedidos"

urlpatterns = [
    path("", views.PedidoListaView.as_view(), name="pedido_lista"),
    path("nuevo/", views.pedido_crear_view, name="pedido_crear"),
    path("<int:pk>/", views.PedidoDetalleView.as_view(), name="pedido_detalle"),
    path("<int:pk>/estado/<str:nuevo_estado>/", views.pedido_cambiar_estado_view, name="pedido_cambiar_estado"),
    path("cocina/", views.PedidoCocinaView.as_view(), name="pedido_cocina"),

]
