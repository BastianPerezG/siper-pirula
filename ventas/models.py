from django.db import models
from inventario.models import Producto, MovimientoInventario
# Create your models here.


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

    class Meta:
        db_table = "venta_item"

    def __str__(self):
        return f"{self.cantidad} x {self.producto.nombre} en Venta #{self.venta_id}"

    @property
    def subtotal(self):
        return self.cantidad * self.precio_unit

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