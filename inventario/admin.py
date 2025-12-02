from django.contrib import admin
from .models import Categoria, Producto, MovimientoInventario, Promo, PromoItem, Proveedor, Compra, CompraItem
# Register your models here.


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("id", "nombre")
    search_fields = ("nombre",)


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("id", "nombre", "ean", "precio", "activo")
    list_filter = ("categoria", "activo")
    search_fields = ("nombre", "ean", "sku")

# Admin Inventario 

@admin.register(MovimientoInventario)
class MovimientoInventarioAdmin(admin.ModelAdmin):
    list_display = ("id", "producto", "tipo", "cantidad", "fecha")
    list_filter = ("tipo", "fecha")
    search_fields = ("producto__nombre", "producto__ean")


class CompraItemInline(admin.TabularInline):
    model = CompraItem
    extra = 1


@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "contacto", "telefono", "correo", "activo")
    list_filter = ("activo",)
    search_fields = ("nombre", "contacto", "correo")


@admin.register(Compra)
class CompraAdmin(admin.ModelAdmin):
    list_display = ("id", "fecha", "proveedor", "doc_tipo", "doc_num")
    list_filter = ("doc_tipo", "proveedor", "fecha")
    search_fields = ("doc_num", "proveedor__nombre")
    inlines = [CompraItemInline]

class PromoItemInline(admin.TabularInline):
    model = PromoItem
    extra = 1


@admin.register(Promo)
class PromoAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "negocio",
        "precio_combo",
        "precio_normal_display",
        "ahorro_display",
        "activo",
        "vigente_hoy",
        "mostrar_en_portada",
    )
    list_filter = ("negocio", "activo", "mostrar_en_portada")
    search_fields = ("nombre", "descripcion")
    inlines = [PromoItemInline]

    def precio_normal_display(self, obj):
        return obj.precio_normal
    precio_normal_display.short_description = "Precio normal"

    def ahorro_display(self, obj):
        return obj.ahorro_estimado
    ahorro_display.short_description = "Ahorro"

    def vigente_hoy(self, obj):
        return obj.esta_vigente()
    vigente_hoy.boolean = True
    vigente_hoy.short_description = "Vigente hoy"