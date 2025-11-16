from django.db import models
from django.db.models import Sum, Case, When, IntegerField, F
from django.core.exceptions import ValidationError

# Create your models here.

class Categoria(models.Model):
    nombre = models.CharField(max_length=80)

    class Meta:
        db_table = "categoria"

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    sku = models.CharField(max_length=40, blank=True, null=True)
    ean = models.CharField("Código de barras", max_length=40, unique=True)
    nombre = models.CharField(max_length=120)
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT)
    precio = models.PositiveIntegerField(default=0, help_text="Precio de venta en pesos chilenos")
    costo = models.PositiveIntegerField(default=0, help_text="Costo en pesos chilenos")
    stock_min = models.IntegerField(default=0)
    ubicacion = models.CharField(max_length=60, blank=True, null=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "producto"

    def __str__(self):
        return f"{self.nombre} ({self.ean})"

    @property
    def stock_actual(self):
        """
        Calcula el stock actual a partir de todos los movimientos.
        ENTRADA y AJUSTE suman, SALIDA y MERMA restan.
        """

        resultado = self.movimientos.aggregate(
            total=Sum(
                Case(
                    When(tipo__in=[MovimientoInventario.TIPO_ENTRADA, MovimientoInventario.TIPO_AJUSTE],
                         then=F("cantidad")),
                    When(tipo__in=[MovimientoInventario.TIPO_SALIDA, MovimientoInventario.TIPO_MERMA],
                         then=-F("cantidad")),
                    default=0,
                    output_field=IntegerField(),
                )
            )
        )
        return resultado["total"] or 0
      

class MovimientoInventario(models.Model):
    TIPO_ENTRADA = "ENTRADA"
    TIPO_SALIDA = "SALIDA"
    TIPO_AJUSTE = "AJUSTE"
    TIPO_MERMA = "MERMA"

    TIPO_CHOICES = [
        (TIPO_ENTRADA, "Entrada (compra, devolución)"),
        (TIPO_SALIDA, "Salida (venta manual, uso interno)"),
        (TIPO_AJUSTE, "Ajuste (conteo inventario)"),
        (TIPO_MERMA, "Merma (rotura, pérdida)"),
    ]

    producto = models.ForeignKey(
        "Producto",
        on_delete=models.PROTECT,
        related_name="movimientos",
    )
    fecha = models.DateTimeField(auto_now_add=True)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    cantidad = models.PositiveIntegerField()
    comentario = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        db_table = "movimiento_inventario"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.tipo} {self.cantidad} de {self.producto.nombre} [{self.fecha}]"