from django.db import models
from inventario.models import Producto, MovimientoInventario
from django.core.exceptions import ValidationError
from core.models import Negocio
from django.conf import settings

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
    
    EST_ABIERTA = "ABIERTA"
    EST_CERRADA = "CERRADA"
    EST_ANULADA = "ANULADA"

    ESTADO_CHOICES = [
        (EST_ABIERTA, "Abierta"),
        (EST_CERRADA, "Cerrada"),
        (EST_ANULADA, "Anulada"),
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

    class Meta:
        db_table = "venta"
        ordering = ["-fecha"]

    def __str__(self):
        return f"Venta #{self.id} - {self.fecha}"

    @property
    def total(self):
        return sum(item.subtotal for item in self.items.all())
    

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
        Al crear un VentaItem, generamos un MovimientoInventario de SALIDA.
        Suposición: los ítems no se editan; si hay error, se borran y se crean de nuevo.
        """
        es_nuevo = self.pk is None
        super().save(*args, **kwargs)

        if es_nuevo:
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