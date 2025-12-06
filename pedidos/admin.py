from django.contrib import admin
from .models import Cliente, Pedido
# Register your models here.

@admin.register(Cliente)
class clieteAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "nombre", "rut", "correo", "telefono", "direccion", "activo")
    list_filter = ("rut", "activo")
    search_fields = ("nombre", "rut")


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    # Campos que se muestran en la lista de pedidos del admin
    list_display = ('id','codigo', 'negocio', 'cliente', 'fecha','nombre')
    
    # Campos por los que se puede filtrar la lista (barra lateral derecha)
    list_filter = ('estado', 'fecha', 'negocio')
    
    # Campos por los que se puede buscar texto
    search_fields = ('codigo', 'cliente_nombre', 'cliente_email')
    