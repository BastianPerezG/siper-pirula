from django.contrib import admin
from .models import Cliente, Pedido, PedidoItem, PedidoEstadoLog
# Register your models here.

@admin.register(Cliente)
class clieteAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "nombre", "rut", "correo", "telefono", "direccion", "activo")
    list_filter = ("rut", "activo")
    search_fields = ("nombre", "rut")


class PedidoItemInline(admin.TabularInline):
    model = PedidoItem
    extra = 0
    readonly_fields = ("producto", "cantidad", "precio")
    can_delete = False


class PedidoEstadoLogInline(admin.TabularInline):
    model = PedidoEstadoLog
    extra = 0
    readonly_fields = ("tipo_estado", "estado", "fecha", "usuario")
    can_delete = False
    ordering = ("-fecha",)


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    # Campos que se muestran en la lista de pedidos del admin
    list_display = (
        'codigo', 
        'cliente_nombre_display',
        'fecha',
        'estado_pago',
        'estado_preparacion',
        'total_monto',
        'forma_pago'
    )
    
    # Campos por los que se puede filtrar la lista (barra lateral derecha)
    list_filter = (
        'estado_pago',
        'estado_preparacion',
        'forma_pago',
        'fecha',
        'negocio'
    )
    
    # Campos por los que se puede buscar texto
    search_fields = ('codigo', 'nombre', 'correo', 'telefono')
    
    # Campos de solo lectura
    readonly_fields = (
        'codigo',
        'fecha',
        'total_monto',
        'webpay_token',
        'webpay_status',
        'estado'  # Mantener visible pero readonly por compatibilidad
    )
    
    # Organización en secciones
    fieldsets = (
        ("Información del Pedido", {
            "fields": ("codigo", "negocio", "cliente", "fecha")
        }),
        ("Estados", {
            "fields": ("estado_preparacion", "estado_pago", "estado"),
            "description": "Estado de preparación: flujo del pedido. Estado de pago: estado del pago."
        }),
        ("Datos de Contacto", {
            "fields": ("nombre", "correo", "telefono")
        }),
        ("Pago", {
            "fields": ("forma_pago", "total_monto", "webpay_token", "webpay_status", "terminos_aceptados")
        }),
    )
    
    inlines = [PedidoItemInline, PedidoEstadoLogInline]
    
    def cliente_nombre_display(self, obj):
        """Muestra el nombre del cliente o el nombre del pedido si no hay cliente"""
        if obj.cliente:
            return obj.cliente.nombre
        return obj.nombre or "Sin nombre"
    cliente_nombre_display.short_description = "Cliente"
