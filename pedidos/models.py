from django.db import models
from django.conf import settings
from pedidos.emails import enviar_correo_cambio_estado
from core.models import Negocio
from inventario.models import Producto, MovimientoInventario
from pedidos.validators import validar_rut
import random
import string

# Modelo Pedidos

class Cliente(models.Model):
    negocio = models.ForeignKey(
        Negocio,
        on_delete=models.PROTECT,
        related_name="clientes",
    )

    # Opcional: usuario Django asociado (para login/registro)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cliente_perfil",
    )

    nombre = models.CharField(max_length=120)

    rut = models.CharField(
        max_length=12,
        blank=True,
        null=True,
        help_text="RUT chileno, ej: 12.345.678-9",
        validators=[validar_rut],
    )

    correo = models.EmailField(blank=True, null=True)
    telefono = models.CharField(max_length=40, blank=True, null=True)

    direccion = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Dirección principal para retiro/envío",
    )

    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "cliente"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Pedido(models.Model):

    # Forma de pago
    FORMA_RETIRO = "RETIRO"
    FORMA_WEBPAY = "WEBPAY"

    FORMA_PAGO_CHOICES = [
        (FORMA_RETIRO, "Pagar al retirar"),
        (FORMA_WEBPAY, "Pago online Webpay"),
    ]

    forma_pago = models.CharField(
        max_length=10,
        choices=FORMA_PAGO_CHOICES,
        default=FORMA_RETIRO,
    )

    # Estados
    EST_RECIBIDO = "RECIBIDO"
    EST_PREPARANDO = "PREPARANDO"
    EST_LISTO = "LISTO"
    EST_RETIRADO = "RETIRADO"
    EST_CANCELADO = "CANCELADO"
    EST_NO_RETIRA = "NO_RETIRA"
    EST_PAGADO = "PAGADO"    

    ESTADO_CHOICES = [
        (EST_RECIBIDO, "Recibido"),
        (EST_PAGADO, "Pagado"),
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

        # Datos Webpay (opcionales)
    webpay_token = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Token de la transacción Webpay"
    )
    webpay_status = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Estado interno del pago Webpay (iniciado, autorizado, etc.)"
    )


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
        enviar_correo_cambio_estado(self)


        # --- Integración con inventario (reservas de stock) ---

    def crear_reservas_inventario(self):
        """
        Crea un MovimientoInventario.TIPO_RESERVA por cada ítem del pedido.
        Esto descuenta stock mientras el pedido está pendiente de retiro.
        """
        for item in self.items.select_related("producto"):
            MovimientoInventario.objects.create(
                producto=item.producto,
                tipo=MovimientoInventario.TIPO_RESERVA,
                cantidad=item.cantidad,
                pedido_item=item,
                comentario=f"Reserva por pedido {self.codigo}",
            )

    def liberar_reservas_inventario(self):
        """
        Elimina las reservas asociadas a este pedido.
        Se usa cuando el pedido se cancela o el cliente no retira.
        """
        MovimientoInventario.objects.filter(
            pedido_item__pedido=self,
            tipo=MovimientoInventario.TIPO_RESERVA,
        ).delete()

    def marcar_pagado_descontar_stock(self, usuario=None):
        """
        Se llama cuando Webpay confirma el pago.
        - Marca el pedido como PAGADO.
        - Por ahora NO tocamos las reservas de inventario porque ya
          se descuentan al crear el pedido.
        """
        # Si quisieras hacer algo extra con inventario, este es el lugar.
        # De momento sólo cambiamos el estado y registramos en el log.
        self.actualizar_total()
        self.cambiar_estado(self.EST_PAGADO, usuario=usuario)
    
    def marcar_cancelado_revertir_reserva(self, usuario=None):
        """
        Se usa cuando Webpay rechaza, expira o el usuario cancela el pago.
        Debe devolver el stock que estaba reservado y marcar el pedido como CANCELADO.
        """
        # 1) Devolver stock (elimina los movimientos de tipo RESERVA)
        self.liberar_reservas_inventario()

        # 2) Marcar el pedido como cancelado y registrar en el log
        self.cambiar_estado(self.EST_CANCELADO, usuario=usuario)
    
    def marcar_pendiente_retiro(self, usuario=None):
        """
        Caso: pedido con pago al retirar en la botillería.
        - Crea las reservas de inventario.
        - Deja el pedido en estado 'RECIBIDO'.
        """
        # Reservar stock para este pedido
        self.crear_reservas_inventario()

        # Actualizar estado
        self.estado = self.EST_RECIBIDO
        self.save(update_fields=["estado"])
    
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
