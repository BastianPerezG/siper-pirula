from django.contrib import admin
from .models import Negocio, PerfilUsuario, BitacoraAccion

# Admin Core
import json
from django.utils.safestring import mark_safe

@admin.register(Negocio)
class NegocioAdmin(admin.ModelAdmin):
    list_display = ("nombre", "rut", "activo")
    list_filter = ("activo",)
    search_fields = ("nombre", "rut")

@admin.register(PerfilUsuario)
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
# core/admin.py


@admin.register(BitacoraAccion)
class BitacoraAccionAdmin(admin.ModelAdmin):
    list_display = ('fecha_hora', 'usuario', 'accion', 'entidad_id', 'detalles_formateados')
    list_filter = ('fecha_hora', 'usuario')
    search_fields = ('accion', 'entidad_id', 'detalles')
    readonly_fields = ('fecha_hora', 'usuario', 'accion', 'entidad_id', 'detalles')
    
    # Desactiva la opción de agregar/editar para forzar la inmutabilidad de la bitácora
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
        
    # Función para mostrar el JSON de forma legible en el admin
    def detalles_formateados(self, obj):
        pretty_json = json.dumps(obj.detalles, indent=4, sort_keys=True)
        # Usar <pre> y mark_safe para que se vea bien en el HTML
        return mark_safe(f'<pre>{pretty_json}</pre>')

    detalles_formateados.short_description = 'Detalles'