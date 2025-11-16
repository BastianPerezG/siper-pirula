from django.contrib import admin
from .models import Categoria, Producto, MovimientoInventario
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


@admin.register(MovimientoInventario)
class MovimientoInventarioAdmin(admin.ModelAdmin):
    list_display = ("id", "producto", "tipo", "cantidad", "fecha")
    list_filter = ("tipo", "fecha")
    search_fields = ("producto__nombre", "producto__ean")