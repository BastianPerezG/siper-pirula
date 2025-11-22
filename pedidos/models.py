from django.db import models
from core.models import Negocio
from inventario.models import Producto
from django.conf import settings


# Modelo Pedidos


class Cliente(models.Model):
    negocio = models.ForeignKey(Negocio, on_delete=models.PROTECT)
    nombre = models.CharField(max_length=120)
    correo = models.EmailField(blank=True, null=True)
    telefono = models.CharField(max_length=40, blank=True, null=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "cliente"

    def __str__(self):
        return self.nombre


class Pedido(models.Model):
    EST_RECIBIDO = "RECIBIDO"
    EST_PREPARANDO = "PREPARANDO"
    EST_LISTO = "LISTO"
    EST_RETIRADO = "RETIRADO"
    EST_CANCELADO = "CANCELADO"
    EST_NO_RETIRA = "NO_RETIRA"

    ESTADO_CHOICES = [
        (EST_RECIBIDO, "Recibido"),
        (EST_PREPARANDO, "Preparando"),
        (EST_LISTO, "Listo"),
        (EST_RETIRADO, "Retirado"),
        (EST_CANCELADO, "Cancelado"),
        (EST_NO_RETIRA, "No retira"),
    ]

    negocio = models.ForeignKey(Negocio, on_delete=models.PROTECT)
    codigo = models.CharField(max_length=16, unique=True)
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    fecha = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default=EST_RECIBIDO)
    total = models.PositiveIntegerField(default=0)

    # Datos de contacto rápidos (por si no hay cliente formal)
    nombre = models.CharField(max_length=120, blank=True, null=True)
    correo = models.EmailField(blank=True, null=True)
    telefono = models.CharField(max_length=40, blank=True, null=True)

    class Meta:
        db_table = "pedido"

    def __str__(self):
        return f"Pedido {self.codigo} - {self.estado}"


class PedidoItem(models.Model):
    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.CASCADE,
        related_name="items",
    )
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField()
    precio = models.PositiveIntegerField()

    class Meta:
        db_table = "pedido_item"

    @property
    def subtotal(self):
        return self.cantidad * self.precio
    

class PedidoEstadoLog(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="estado_logs")
    estado = models.CharField(max_length=20)
    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "pedido_estado_log"