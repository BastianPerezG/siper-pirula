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
    usuario_desbloquear_view,
    BitacoraListView,
    bitacora_export_csv,
    bitacora_export_pdf,
    bitacora_detalle_view,
    CustomPasswordResetView,
)

app_name = "core"

urlpatterns = [
    path("login/", login_interno_view, name="login_interno"),
    path("logout/", logout_interno_view, name="logout_interno"),
    path("password_reset/", CustomPasswordResetView.as_view(), name="password_reset_custom"),
    path("", DashboardView.as_view(), name="dashboard"),

    # Gestión de usuarios internos (solo admin)
    path("usuarios/", UsuarioListaView.as_view(), name="usuarios_lista"),
    path("usuarios/nuevo/", UsuarioCrearView.as_view(), name="usuario_crear"),
    path("usuarios/<int:pk>/editar/", UsuarioEditarView.as_view(), name="usuario_editar"),
    path("usuarios/<int:pk>/toggle-activo/", usuario_toggle_activo_view, name="usuario_toggle_activo"),
    path("usuarios/<int:pk>/desbloquear/", usuario_desbloquear_view, name="usuario_desbloquear"),
    
    # Bitácora
    path("administracion/bitacora/", BitacoraListView.as_view(), name="admin_bitacoras"),
    path("administracion/bitacora/<int:pk>/", bitacora_detalle_view, name="bitacora_detalle"),
    path("administracion/bitacora/export/csv/", bitacora_export_csv, name="bitacora_export_csv"),
    path("administracion/bitacora/export/pdf/", bitacora_export_pdf, name="bitacora_export_pdf"),

]