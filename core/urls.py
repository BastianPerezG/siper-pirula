from django.urls import path
from .views import DashboardView
from .views import (
    DashboardView,
    login_interno_view,
    logout_interno_view,
    UsuarioListaView,
    UsuarioCrearView,
    UsuarioEditarView,
    usuario_toggle_activo_view,
)

app_name = "core"

urlpatterns = [
    path("login/", login_interno_view, name="login_interno"),
    path("logout/", logout_interno_view, name="logout_interno"),
    path("", DashboardView.as_view(), name="dashboard"),

    # Gestión de usuarios internos (solo admin)
    path("usuarios/", UsuarioListaView.as_view(), name="usuarios_lista"),
    path("usuarios/nuevo/", UsuarioCrearView.as_view(), name="usuario_crear"),
    path("usuarios/<int:pk>/editar/", UsuarioEditarView.as_view(), name="usuario_editar"),
    path("usuarios/<int:pk>/toggle-activo/", usuario_toggle_activo_view, name="usuario_toggle_activo"),
]