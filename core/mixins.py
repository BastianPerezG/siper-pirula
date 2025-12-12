# core/mixins.py
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from functools import wraps

def _get_perfil(user):
    return getattr(user, "perfilusuario", None)

class RolRequeridoMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Mixin para CBVs. Define `roles_requeridos = ["ADMIN", "CAJERO"]`, etc.
    """
    roles_requeridos = None  # lista de códigos de rol

    def test_func(self):
        user = self.request.user
        perfil = _get_perfil(user)
        if not user.is_authenticated or not perfil:
            return False
        if not user.is_active or not perfil.activo:
            return False
        if self.roles_requeridos is None:
            return True
        return perfil.rol in self.roles_requeridos
    
    def handle_no_permission(self):
        """Renderiza el template 403 en lugar de lanzar excepción."""
        return render(self.request, "403.html", status=403)


def rol_requerido(*roles):
    """
    Decorador para FBVs.
    Uso:
        @rol_requerido("ADMIN")
        def vista_x(request): ... 

        @rol_requerido("ADMIN", "CAJERO")
        def vista_y(request): ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user
            perfil = _get_perfil(user)
            if not user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login
                return redirect_to_login(request.get_full_path())

            if not perfil or not user.is_active or not perfil.activo:
                return render(request, "403.html", status=403)

            if roles and perfil.rol not in roles:
                return render(request, "403.html", status=403)

            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
