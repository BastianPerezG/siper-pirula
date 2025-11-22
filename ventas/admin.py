from django.contrib import admin
from .models import Venta, VentaItem

# Admin Ventas.


class VentaItemInline(admin.TabularInline):
    model = VentaItem
    extra = 0


@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    list_display = ("id", "fecha", "negocio", "doc_tipo", "doc_num", "medio_pago", "total")
    list_filter = ("negocio", "doc_tipo", "medio_pago")
    date_hierarchy = "fecha"
    inlines = [VentaItemInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Superusuario ve todo
        if request.user.is_superuser:
            return qs
        # Usuario normal sólo ve su negocio
        if hasattr(request.user, "perfilusuario"):
            return qs.filter(negocio=request.user.perfilusuario.negocio)
        return qs.none()
