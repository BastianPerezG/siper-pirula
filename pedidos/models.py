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

    # Estados de preparación del pedido (workflow de preparación)
    PREP_RECIBIDO = "RECIBIDO"
    PREP_PREPARANDO = "PREPARANDO"
    PREP_LISTO = "LISTO"
    PREP_RETIRADO = "RETIRADO"
    PREP_CANCELADO = "CANCELADO"
    PREP_NO_RETIRA = "NO_RETIRA"

    ESTADO_PREPARACION_CHOICES = [
        (PREP_RECIBIDO, "Recibido"),
        (PREP_PREPARANDO, "Preparando"),
        (PREP_LISTO, "Listo para retiro"),
        (PREP_RETIRADO, "Retirado"),
        (PREP_CANCELADO, "Cancelado"),
        (PREP_NO_RETIRA, "No retira"),
    ]

    # Estados de pago
    PAGO_PENDIENTE = "PENDIENTE"
    PAGO_PAGADO = "PAGADO"
    PAGO_CANCELADO = "CANCELADO"

    ESTADO_PAGO_CHOICES = [
        (PAGO_PENDIENTE, "Pendiente de pago"),
        (PAGO_PAGADO, "Pagado"),
        (PAGO_CANCELADO, "Pago cancelado"),
    ]

    # Mantener constantes antiguas para compatibilidad temporal
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
    
    # Nuevos campos de estado separados
    estado_preparacion = models.CharField(
        max_length=20,
        choices=ESTADO_PREPARACION_CHOICES,
        default=PREP_RECIBIDO,
        verbose_name="Estado de preparación"
    )
    
    estado_pago = models.CharField(
        max_length=20,
        choices=ESTADO_PAGO_CHOICES,
        default=PAGO_PENDIENTE,
        verbose_name="Estado de pago"
    )
    
    # Mantener campo antiguo por compatibilidad (será eliminado después)
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

    terminos_aceptados = models.BooleanField(
        default=False,
        help_text="Indica si el cliente aceptó los términos al comprar."
    )


    class Meta:
        db_table = "pedido"
        ordering = ["-fecha"]

    def __str__(self):
        return f"Pedido {self.codigo} - Prep: {self.get_estado_preparacion_display()}, Pago: {self.get_estado_pago_display()}"

    @property
    def total(self) -> int:
        """Suma de todos los ítems."""
        return sum(item.subtotal for item in self.items.all())

    def actualizar_total(self, guardar=True):
        self.total_monto = self.total
        if guardar:
            self.save(update_fields=["total_monto"])

    def cambiar_estado(self, nuevo_estado, usuario=None):
        """Helper centralizado para cambiar estado + log (mantener por compatibilidad)."""
        self.estado = nuevo_estado
        self.save(update_fields=["estado"])
        PedidoEstadoLog.objects.create(
            pedido=self,
            estado=nuevo_estado,
            usuario=usuario,
            tipo_estado="PREPARACION",  # Por defecto
        )
        enviar_correo_cambio_estado(self)
    
    def cambiar_estado_preparacion(self, nuevo_estado, usuario=None):
        """Cambia el estado de preparación del pedido."""
        self.estado_preparacion = nuevo_estado
        # También actualizar estado antiguo por compatibilidad
        if nuevo_estado != self.PREP_RECIBIDO or self.estado_pago != self.PAGO_PAGADO:
            self.estado = nuevo_estado
        self.save(update_fields=["estado_preparacion", "estado"])
        PedidoEstadoLog.objects.create(
            pedido=self,
            estado=nuevo_estado,
            usuario=usuario,
            tipo_estado="PREPARACION",
        )
        enviar_correo_cambio_estado(self)
    
    def cambiar_estado_pago(self, nuevo_estado, usuario=None):
        """Cambia el estado de pago del pedido."""
        self.estado_pago = nuevo_estado
        # También actualizar estado antiguo por compatibilidad
        if nuevo_estado == self.PAGO_PAGADO:
            self.estado = self.EST_PAGADO
        self.save(update_fields=["estado_pago", "estado"])
        PedidoEstadoLog.objects.create(
            pedido=self,
            estado=nuevo_estado,
            usuario=usuario,
            tipo_estado="PAGO",
        )
        enviar_correo_cambio_estado(self)


        # --- Integración con inventario (reservas de stock) ---

    def crear_reservas_inventario(self):
        """
        Crea un MovimientoInventario.TIPO_RESERVA por cada ítem del pedido.
        Esto descuenta stock mientras el pedido está pendiente de retiro.
        Valida que haya stock suficiente antes de crear las reservas.
        """
        from django.core.exceptions import ValidationError
        
        # Primero validar que hay stock suficiente para todos los productos
        for item in self.items.select_related("producto"):
            stock_actual = item.producto.stock_actual
            if item.cantidad > stock_actual:
                raise ValidationError(
                    f"No hay stock suficiente de '{item.producto.nombre}'. "
                    f"Disponible: {stock_actual}, Solicitado: {item.cantidad}"
                )
        
        # Si la validación pasa, crear las reservas
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
        - Marca el estado_pago como PAGADO.
        - Mantiene el estado_preparacion como RECIBIDO para que el funcionario pueda gestionarlo.
        - Por ahora NO tocamos las reservas de inventario porque ya
          se descuentan al crear el pedido.
        """
        self.actualizar_total()
        self.cambiar_estado_pago(self.PAGO_PAGADO, usuario=usuario)
    
    def marcar_cancelado_revertir_reserva(self, usuario=None):
        """
        Se usa cuando Webpay rechaza, expira o el usuario cancela el pago.
        Debe devolver el stock que estaba reservado y marcar el pedido como CANCELADO.
        """
        # 1) Devolver stock (elimina los movimientos de tipo RESERVA)
        self.liberar_reservas_inventario()

        # 2) Marcar ambos estados como cancelado
        self.estado_pago = self.PAGO_CANCELADO
        self.estado_preparacion = self.PREP_CANCELADO
        self.estado = self.EST_CANCELADO  # Compatibilidad
        self.save(update_fields=["estado_pago", "estado_preparacion", "estado"])
        
        # 3) Registrar en el log
        PedidoEstadoLog.objects.create(
            pedido=self,
            estado=self.PAGO_CANCELADO,
            usuario=usuario,
            tipo_estado="PAGO",
        )
        PedidoEstadoLog.objects.create(
            pedido=self,
            estado=self.PREP_CANCELADO,
            usuario=usuario,
            tipo_estado="PREPARACION",
        )
        enviar_correo_cambio_estado(self)
    
    def marcar_pendiente_retiro(self, usuario=None):
        """
        Caso: pedido con pago al retirar en la botillería.
        - Crea las reservas de inventario.
        - Deja el pedido en estado 'RECIBIDO' para preparación y 'PENDIENTE' para pago.
        """
        # Reservar stock para este pedido
        self.crear_reservas_inventario()

        # Actualizar estados
        self.estado_preparacion = self.PREP_RECIBIDO
        self.estado_pago = self.PAGO_PENDIENTE
        self.estado = self.EST_RECIBIDO  # Compatibilidad
        self.save(update_fields=["estado_preparacion", "estado_pago", "estado"])
    
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
    TIPO_PREPARACION = "PREPARACION"
    TIPO_PAGO = "PAGO"
    
    TIPO_ESTADO_CHOICES = [
        (TIPO_PREPARACION, "Estado de preparación"),
        (TIPO_PAGO, "Estado de pago"),
    ]
    
    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.CASCADE,
        related_name="estado_log",
    )
    tipo_estado = models.CharField(
        max_length=20,
        choices=TIPO_ESTADO_CHOICES,
        default=TIPO_PREPARACION,
        verbose_name="Tipo de estado"
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
        return f"{self.pedido.codigo} → {self.get_tipo_estado_display()}: {self.estado} @ {self.fecha}"
