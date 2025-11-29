from django.contrib import admin
from .models import Cliente
# Register your models here.

@admin.register(Cliente)
class clieteAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "nombre", "rut", "correo", "telefono", "direccion", "activo")
    list_filter = ("rut", "activo")
    search_fields = ("nombre", "rut")
