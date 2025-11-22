from django.contrib import admin
from .models import Negocio, PerfilUsuario

# Admin Core

@admin.register(Negocio)
class NegocioAdmin(admin.ModelAdmin):
    list_display = ("nombre", "rut", "activo")
    list_filter = ("activo",)
    search_fields = ("nombre", "rut")


class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ("user", "negocio")
    search_fields = ("user__username", "negocio__nombre")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Opcional: si no quieres que usuarios “staff” vean perfiles de otros negocios
        if request.user.is_superuser:
            return qs
        if hasattr(request.user, "perfilusuario"):
            return qs.filter(negocio=request.user.perfilusuario.negocio)
        return qs.none()
