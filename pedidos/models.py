from django.db import models
from django.conf import settings

from core.models import Negocio
from inventario.models import Producto

import random
import string

# Modelo Pedidos

class Cliente(models.Model):
    negocio = models.ForeignKey(
        Negocio,
        on_delete=models.PROTECT,
        related_name="clientes",
    )
    nombre = models.CharField(max_length=120)
    correo = models.EmailField(blank=True, null=True)
    telefono = models.CharField(max_length=40, blank=True, null=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "cliente"
        ordering = ["nombre"]

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
        (EST_LISTO, "Listo para retiro"),
        (EST_RETIRADO, "Retirado"),
        (EST_CANCELADO, "Cancelado"),
        (EST_NO_RETIRA, "No retira"),
    ]

    negocio = models.ForeignKey(
        Negocio,
        on_delete=models.PROTECT,
        related_name="pedidos",
    )
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pedidos",
    )

    codigo = models.CharField(
        max_length=16,
        unique=True,
        help_text="Código corto para mostrar al cliente (ej: ABC123).",
    )

    fecha = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default=EST_RECIBIDO,
    )

    # Datos de contacto (para pedidos rápidos sin registrar cliente formal)
    nombre = models.CharField(max_length=120, blank=True, null=True)
    correo = models.EmailField(blank=True, null=True)
    telefono = models.CharField(max_length=40, blank=True, null=True)

    # Campo total opcional (puedes usarlo o sólo el @property)
    total_monto = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "pedido"
        ordering = ["-fecha"]

    def __str__(self):
        return f"Pedido {self.codigo} ({self.get_estado_display()})"

    @property
    def total(self) -> int:
        """Suma de todos los ítems."""
        return sum(item.subtotal for item in self.items.all())

    def actualizar_total(self, guardar=True):
        self.total_monto = self.total
        if guardar:
            self.save(update_fields=["total_monto"])

    def cambiar_estado(self, nuevo_estado, usuario=None):
        """Helper centralizado para cambiar estado + log."""
        self.estado = nuevo_estado
        self.save(update_fields=["estado"])
        PedidoEstadoLog.objects.create(
            pedido=self,
            estado=nuevo_estado,
            usuario=usuario,
        )
    
    def _generar_codigo_unico(self):
        """
        Genera un código tipo ABC123, y se asegura de que no exista ya en la BD.
        """
        while True:
            nuevo = "".join(
                random.choices(string.ascii_uppercase + string.digits, k=6)
            )
            if not Pedido.objects.filter(codigo=nuevo).exists():
                return nuevo

    def save(self, *args, **kwargs):
        if not self.codigo:
            self.codigo = self._generar_codigo_unico()
        super().save(*args, **kwargs)


class PedidoItem(models.Model):
    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.CASCADE,
        related_name="items",
    )
    producto = models.ForeignKey(
        Producto,
        on_delete=models.PROTECT,
        related_name="pedido_items",
    )
    cantidad = models.PositiveIntegerField()
    precio = models.PositiveIntegerField(
        help_text="Precio unitario en pesos chilenos.",
    )

    class Meta:
        db_table = "pedido_item"

    def __str__(self):
        return f"{self.cantidad} x {self.producto.nombre} ({self.pedido.codigo})"

    @property
    def subtotal(self) -> int:
        return self.cantidad * self.precio


class PedidoEstadoLog(models.Model):
    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.CASCADE,
        related_name="estado_log",
    )
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
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.pedido.codigo} → {self.estado} @ {self.fecha}"
