from django.contrib import admin
from .models import Venta, VentaItem

# Register your models here.


class VentaItemInline(admin.TabularInline):
    model = VentaItem
    extra = 0


@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    list_display = ("id", "fecha", "doc_tipo", "doc_num", "medio_pago", "total")
    inlines = [VentaItemInline]
