from django.db import models
from inventario.models import Producto, MovimientoInventario
from django.core.exceptions import ValidationError
from django.db.models import Sum, Q 
from core.models import Negocio
from django.conf import settings
from decimal import Decimal
from django.utils import timezone

# Modelo Ventas


class Venta(models.Model):
    DOC_BOLETA = "BOLETA"
    DOC_FACTURA = "FACTURA"
    DOC_SIN_DOC = "SIN_DOC"

    DOC_TIPO_CHOICES = [
        (DOC_BOLETA, "Boleta"),
        (DOC_FACTURA, "Factura"),
        (DOC_SIN_DOC, "Sin documento"),
    ]

    MED_EFECTIVO = "EFECTIVO"
    MED_DEBITO = "DEBITO"
    MED_CREDITO = "CREDITO"
    MED_TRANSFERENCIA = "TRANSFERENCIA"

    MEDIO_PAGO_CHOICES = [
        (MED_EFECTIVO, "Efectivo"),
        (MED_DEBITO, "Tarjeta débito"),
        (MED_CREDITO, "Tarjeta crédito"),
        (MED_TRANSFERENCIA, "Transferencia"),
    ]
    
    # Estados de la Venta
    EST_ABIERTA = "ABIERTA"
    EST_CERRADA = "CERRADA"
    EST_ANULADA = "ANULADA"

    ESTADO_CHOICES = [
        (EST_ABIERTA, "Abierta"),  # "Venta en espera" (armada pero no cobrada)
        (EST_CERRADA, "Cerrada"),  # Venta pagada / cerrada en caja
        (EST_ANULADA, "Anulada"),  # Venta anulada (stock revertido)
    ]
    negocio = models.ForeignKey(Negocio, on_delete=models.PROTECT)
    fecha = models.DateTimeField(auto_now_add=True)
    doc_tipo = models.CharField(
        max_length=10,
        choices=DOC_TIPO_CHOICES,
        default=DOC_BOLETA,
    )
    doc_num = models.CharField(
        "Número documento",
        max_length=20,
        blank=True,
        null=True,
    )
    medio_pago = models.CharField(
        max_length=15,
        choices=MEDIO_PAGO_CHOICES,
        default=MED_EFECTIVO,
    )
    comentario = models.CharField(max_length=200, blank=True, null=True)

    estado = models.CharField(
        max_length=10,
        choices=ESTADO_CHOICES,
        default=EST_CERRADA,  # o ABIERTA, según flujo
    )

    pedido = models.ForeignKey(
        "pedidos.Pedido",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ventas",
    )
    monto_total = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0, 
        help_text="Monto total final de la venta (suma de subtotales de ítems)."
    )
    class Meta:
        db_table = "venta"
        ordering = ["-fecha"]

    def __str__(self):
        return f"Venta #{self.id} - {self.fecha}"

    @property
    def total(self):
        """
        Suma los subtotales de todos los items de la venta.

        Ojo:
        - Para ventas "en espera" también calcula el total,
          pero el significado contable (cobrada/no cobrada)
          depende del campo `estado`.
        """
        return sum(item.subtotal for item in self.items.all())
    
    def cerrar_y_actualizar_stock(self):
        """
        Cierra una venta en espera:
        - Convierte reservas (TIPO_RESERVA) asociadas a cada VentaItem en SALIDA.
        - Si no existieran reservas (caso extraño), crea las salidas directamente.
        - Actualiza el estado a CERRADA y congela el monto_total.
        """
        if self.estado == self.EST_ANULADA:
            raise ValidationError("No se puede cerrar una venta que ya está anulada.")

        if not self.items.exists():
            raise ValidationError("No se puede cerrar una venta sin ítems.")

        for item in self.items.all():
            # Buscar reservas asociadas a este item
            reservas = MovimientoInventario.objects.filter(
                venta_item=item,
                tipo=MovimientoInventario.TIPO_RESERVA,
            )

            if reservas.exists():
                for mov in reservas:
                    mov.tipo = MovimientoInventario.TIPO_SALIDA
                    comentario_base = mov.comentario or ""
                    extra = f" → Venta cobrada #{self.pk}"
                    mov.comentario = (comentario_base + extra).strip()
                    mov.save(update_fields=["tipo", "comentario"])
            else:
                # Si por alguna razón no hay reserva, generamos la salida directa
                MovimientoInventario.objects.create(
                    producto=item.producto,
                    tipo=MovimientoInventario.TIPO_SALIDA,
                    cantidad=item.cantidad,
                    comentario=f"Venta #{self.pk}",
                    venta_item=item,
                )

        # Actualizar estado y total
        self.monto_total = self.total
        self.estado = self.EST_CERRADA
        self.save(update_fields=["monto_total", "estado"])
    

class VentaItem(models.Model):
    venta = models.ForeignKey(
        Venta,
        related_name="items",
        on_delete=models.CASCADE,
    )
    producto = models.ForeignKey(
        Producto,
        on_delete=models.PROTECT,
    )

    pedido_item = models.ForeignKey(
        "pedidos.PedidoItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="venta_items",
    )

    cantidad = models.PositiveIntegerField()
    precio_unit = models.PositiveIntegerField(
        help_text="Precio de venta en pesos chilenos"
    )

    descuento_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Descuento porcentual sobre este ítem (0–100)",
    )

    class Meta:
        db_table = "venta_item"

    def __str__(self):
        return f"{self.cantidad} x {self.producto.nombre} en Venta #{self.venta_id}"

    @property
    def subtotal_bruto(self):
        """Subtotal sin descuento, solo cantidad x precio."""
        return self.cantidad * self.precio_unit

    @property
    def subtotal(self):
        """Subtotal aplicando descuento_pct, si existe."""
        bruto = self.subtotal_bruto
        if self.descuento_pct:
            return int(bruto * (1 - float(self.descuento_pct) / 100))
        return bruto

    def clean(self):
        """
        Validación de negocio: no permitir vender más cantidad
        que el stock disponible.
        """
        super().clean()

        # Validar stock
        if self.producto and self.cantidad:
            disponible = self.producto.stock_actual  # usa MovimientoInventario
            if self.cantidad > disponible:
                raise ValidationError({
                    "cantidad": f"No hay stock suficiente. Disponible: {disponible} unidades."
                })

        # (opcional) Validar rango del descuento
        if self.descuento_pct is not None:
            if float(self.descuento_pct) < 0 or float(self.descuento_pct) > 100:
                raise ValidationError({
                    "descuento_pct": "El descuento debe estar entre 0 y 100%."
                })

    def save(self, *args, **kwargs):
            """
            Al crear un VentaItem, generamos o reutilizamos Movimientos de Inventario.

            Casos:
            - Venta en espera (venta.estado == EST_ABIERTA):
                Se genera un movimiento TIPO_RESERVA asociado al item.
            - Venta desde Pedido (pedido_item no es None):
                Se buscan las reservas del pedido y se convierten en SALIDA.
            - Venta directa (POS cobrada inmediatamente):
                Se genera una SALIDA normal.
            """
            es_nuevo = self.pk is None
            super().save(*args, **kwargs)

            if not es_nuevo:
                # En esta versión solo manipulamos stock al crear el item.
                return

            # --- Caso venta en espera: reservamos stock, no lo descontamos aún ---
            if self.venta.estado == Venta.EST_ABIERTA:
                MovimientoInventario.objects.create(
                    producto=self.producto,
                    tipo=MovimientoInventario.TIPO_RESERVA,
                    cantidad=self.cantidad,
                    comentario=f"Reserva por Venta en espera #{self.venta_id}",
                    venta_item=self,
                )
                return

            mov_usado = False

            # --- Caso 1: venta originada desde un Pedido ---
            if self.pedido_item_id:
                reservas = MovimientoInventario.objects.filter(
                    pedido_item=self.pedido_item,
                    tipo=MovimientoInventario.TIPO_RESERVA,
                )

                if reservas.exists():
                    for mov in reservas:
                        mov.tipo = MovimientoInventario.TIPO_SALIDA
                        mov.venta_item = self
                        comentario_base = mov.comentario or ""
                        extra = f" → Venta #{self.venta_id}"
                        mov.comentario = (comentario_base + extra).strip()
                        mov.save(update_fields=["tipo", "venta_item", "comentario"])
                    mov_usado = True

            # --- Caso 2: venta directa (o no se encontró ninguna reserva) ---
            if not mov_usado:
                MovimientoInventario.objects.create(
                    producto=self.producto,
                    tipo=MovimientoInventario.TIPO_SALIDA,
                    cantidad=self.cantidad,
                    comentario=f"Venta #{self.venta_id}",
                    venta_item=self,
                )



class Anulacion(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.PROTECT)
    venta_item = models.ForeignKey(
        "VentaItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    motivo = models.CharField(max_length=120)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "anulacion"
    def clean(self):
        super().clean()
        
        # 1. Forzar que siempre haya una Venta asociada.
        if self.venta is None:
            raise ValidationError({'venta': "La anulación debe estar siempre ligada a una Venta principal."})

        # 2. Forzar que venta_item sea NULL (Regla de Anulación Completa)
        if self.venta_item is not None:
            raise ValidationError({
                'venta_item': "Este registro de Anulación solo permite la anulación completa de la Venta. El campo VentaItem debe estar vacío."
            })
    
    def __str__(self):
        # El __str__ ahora confirma que siempre es una anulación total.
        return f"Anulación Total de Venta #{self.venta_id}"
    

class CajaTurno(models.Model):
    EST_ABIERTA = "ABIERTA"
    EST_CERRADA = "CERRADA"

    ESTADO_CHOICES = [
        (EST_ABIERTA, "Abierta"),
        (EST_CERRADA, "Cerrada"),
    ]

    negocio = models.ForeignKey(Negocio, on_delete=models.PROTECT)
    usuario_apertura = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cajas_abiertas",
    )
    fecha_apertura = models.DateTimeField(auto_now_add=True)

    monto_inicial = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Fondo inicial de caja en efectivo.",
    )

    # Datos de cierre
    usuario_cierre = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cajas_cerradas",
    )
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    monto_contado_cierre = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Monto de efectivo contado al cierre.",
    )
    observacion_cierre = models.CharField(
        max_length=200,
        blank=True,
    )

    estado = models.CharField(
        max_length=10,
        choices=ESTADO_CHOICES,
        default=EST_ABIERTA,
    )

    class Meta:
        db_table = "caja_turno"

    def __str__(self):
        return f"Caja {self.negocio.nombre} - {self.fecha_apertura:%Y-%m-%d %H:%M}"

    def clean(self):
        """
        Evita que se creen dos cajas ABIERTAS para el mismo negocio.
        Esta validación se ejecuta cuando se llama a form.is_valid().
        """
        super().clean()

        if self.estado == self.EST_ABIERTA and self.negocio_id:
            qs = CajaTurno.objects.filter(
                negocio=self.negocio,
                estado=self.EST_ABIERTA,
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)

            if qs.exists():
                raise ValidationError(
                    "Ya existe una caja abierta para este negocio. "
                    "Debes cerrarla antes de abrir una nueva."
                )

    # --- Helpers de negocio --- #
    def ventas_del_turno(self):
        """
        Ventas cerradas dentro del rango de este turno (excluye anuladas).
        """
        qs = Venta.objects.filter(
            negocio=self.negocio,
            fecha__gte=self.fecha_apertura,
        ).exclude(estado=Venta.EST_ANULADA)

        if self.fecha_cierre:
            qs = qs.filter(fecha__lte=self.fecha_cierre)

        return qs

    def ventas_por_medio_pago(self):
        """
        Devuelve un queryset agregado con el total por medio de pago.
        """
        return (
            self.ventas_del_turno()
            .values("medio_pago")
            .annotate(monto=Sum("monto_total"))
        )

    def total_ventas(self):
        return self.ventas_del_turno().aggregate(
            total=Sum("monto_total")
        )["total"] or 0

    def monto_esperado_efectivo(self):
        """
        Monto esperado en efectivo:
        fondo inicial + ventas en efectivo del turno.
        (Más adelante podríamos considerar egresos/ingresos de caja).
        """
        ventas_efectivo = self.ventas_del_turno().filter(
            medio_pago=Venta.MED_EFECTIVO
        )
        total_efectivo = ventas_efectivo.aggregate(
            total=Sum("monto_total")
        )["total"] or 0

        return self.monto_inicial + total_efectivo
    
    @property
    def diferencia_cierre(self):
        """
        Diferencia final entre lo esperado y lo contado al cierre.
        Si la caja aún no está cerrada o no se ha contado, devuelve None.
        """
        if self.monto_contado_cierre is None:
            return None
        esperado = self.monto_esperado_efectivo()
        return self.monto_contado_cierre - Decimal(esperado)


class ArqueoParcial(models.Model):
    caja = models.ForeignKey(
        CajaTurno,
        on_delete=models.CASCADE,
        related_name="arqueos",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
    )
    fecha = models.DateTimeField(auto_now_add=True)

    monto_esperado = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )
    monto_contado = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )
    diferencia = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    observacion = models.CharField(
        max_length=200,
        blank=True,
    )

    class Meta:
        db_table = "arqueo_parcial"

    def __str__(self):
        return f"Arqueo parcial {self.caja_id} ({self.fecha:%Y-%m-%d %H:%M})"

try:
    from core.models import PerfilUsuario
    ROL_CHOICES = PerfilUsuario.ROL_CHOICES
except Exception:
    # fallback por si prefieres dejarlo desacoplado
    ROL_CHOICES = [
        ("ROL_CAJERO", "Cajero"),
        ("ROL_MESON", "Mesón"),
        ("ROL_ADMIN", "Administrador"),
    ]

class DescuentoReglaRol(models.Model):
    """
    Regla de tope de descuento según rol del usuario.
    Controla:
      - Máximo porcentaje y monto por ítem.
      - Máximo porcentaje y monto por ticket completo.
    """

    rol = models.CharField(max_length=20, choices=ROL_CHOICES, unique=True)

    # Topes por porcentaje
    max_pct_item = models.DecimalField(
        "Tope % por ítem",
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Ej: 10.00 = 10% máximo que puede aplicar este rol a un ítem.",
    )
    max_pct_venta = models.DecimalField(
        "Tope % por ticket",
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Ej: 5.00 = 5% máximo sobre el total de la venta.",
    )

    # Topes por monto fijo (en pesos)
    max_monto_item = models.PositiveIntegerField(
        "Tope $ por ítem",
        default=0,
        help_text="Monto máximo de descuento en pesos por ítem.",
    )
    max_monto_venta = models.PositiveIntegerField(
        "Tope $ por ticket",
        default=0,
        help_text="Monto máximo de descuento en pesos por venta.",
    )

    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "descuento_regla_rol"
        verbose_name = "Regla de descuento por rol"
        verbose_name_plural = "Reglas de descuento por rol"

    def __str__(self):
        return f"Regla descuentos - {self.get_rol_display()}"
    
class CodigoAutorizacionDescuento(models.Model):
    """
    PIN de autorización para aprobar descuentos que superan el tope de un rol.
    Lo asocias a un usuario con rol superior (SUPERVISOR / ADMIN).
    """

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="codigos_descuento",
    )
    codigo = models.CharField(
        max_length=20,
        help_text="PIN o código corto que se pedirá al cajero.",
    )
    descripcion = models.CharField(
        max_length=200,
        blank=True,
        help_text="Ej: 'Código de supervisor turno tarde'.",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_expiracion = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Opcional. Si se completa, el código no será válido después de esta fecha.",
    )
    activo = models.BooleanField(default=True)
    max_usos = models.PositiveIntegerField(
        default=0,
        help_text="0 = ilimitado. Si es >0, limita la cantidad de usos.",
    )
    usos_realizados = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "codigo_autorizacion_descuento"
        verbose_name = "Código de autorización de descuento"
        verbose_name_plural = "Códigos de autorización de descuentos"

    def __str__(self):
        return f"{self.codigo} ({self.usuario})"

    @property
    def vigente(self) -> bool:
        """
        Indica si el código está activo y no ha expirado ni superado sus usos.
        """
        if not self.activo:
            return False
        if self.fecha_expiracion and self.fecha_expiracion < timezone.now():
            return False
        if self.max_usos and self.usos_realizados >= self.max_usos:
            return False
        return True
    
from django.utils import timezone


class AuditoriaDescuento(models.Model):
    TIPO_PORCENTAJE = "PORCENTAJE"
    TIPO_MONTO = "MONTO"
    TIPO_CHOICES = [
        (TIPO_PORCENTAJE, "Porcentaje"),
        (TIPO_MONTO, "Monto fijo"),
    ]

    NIVEL_ITEM = "ITEM"
    NIVEL_VENTA = "VENTA"
    NIVEL_CHOICES = [
        (NIVEL_ITEM, "Producto / ítem"),
        (NIVEL_VENTA, "Ticket completo"),
    ]

    ESTADO_OK = "OK"
    ESTADO_RECHAZADO = "RECHAZADO"
    ESTADO_INTENTO = "INTENTO_FALLIDO"
    ESTADO_CHOICES = [
        (ESTADO_OK, "Aplicado correctamente"),
        (ESTADO_RECHAZADO, "Rechazado por reglas"),
        (ESTADO_INTENTO, "Intento fallido (PIN incorrecto, etc.)"),
    ]

    # Contexto de la venta
    venta = models.ForeignKey(
        "Venta",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="auditorias_descuentos",
    )
    venta_item = models.ForeignKey(
        "VentaItem",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="auditorias_descuentos",
    )

    # Quién aplica y quién autoriza
    usuario_aplica = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="descuentos_aplicados",
    )
    usuario_autoriza = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="descuentos_autorizados",
    )
    codigo_autorizacion = models.ForeignKey(
        CodigoAutorizacionDescuento,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    # Detalle del descuento
    motivo = models.CharField(max_length=200)
    tipo_descuento = models.CharField(max_length=20, choices=TIPO_CHOICES)
    nivel = models.CharField(max_length=10, choices=NIVEL_CHOICES)

    valor_porcentaje = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    valor_monto = models.PositiveIntegerField(null=True, blank=True)

    monto_original = models.PositiveIntegerField()
    monto_final = models.PositiveIntegerField()

    fecha_hora = models.DateTimeField(default=timezone.now)
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default=ESTADO_OK,
    )

    terminal = models.CharField(
        max_length=100,
        blank=True,
        help_text="Ej: nombre del equipo, IP, etc.",
    )

    class Meta:
        db_table = "auditoria_descuento"
        verbose_name = "Auditoría de descuento"
        verbose_name_plural = "Auditoría de descuentos"
        ordering = ["-fecha_hora"]

    def __str__(self):
        return f"[{self.fecha_hora:%Y-%m-%d %H:%M}] {self.usuario_aplica} - {self.tipo_descuento} {self.valor_porcentaje or self.valor_monto}"
