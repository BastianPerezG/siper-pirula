from django.db import models
from django.db.models import Sum, Case, When, IntegerField, F
from django.core.exceptions import ValidationError
from core.models import Negocio 
from django.utils.text import slugify

# Modelo Inventario.

class Categoria(models.Model):
    negocio = models.ForeignKey(Negocio, on_delete=models.PROTECT)
    nombre = models.CharField(max_length=80)

    slug = models.SlugField(max_length=100, blank=True)
    imagen = models.ImageField(upload_to="categorias/", null=True, blank=True)

    activa = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "categoria"
        ordering = ["orden", "nombre"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nombre)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    negocio = models.ForeignKey(Negocio, on_delete=models.PROTECT)
    sku = models.CharField(max_length=40, blank=True, null=True)
    ean = models.CharField("Código de barras", max_length=40, unique=True)
    nombre = models.CharField(max_length=120)
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT)
    precio = models.PositiveIntegerField(default=0, help_text="Precio de venta en pesos chilenos")
    costo = models.PositiveIntegerField(default=0, help_text="Costo en pesos chilenos")
    stock_min = models.IntegerField(default=0)
    ubicacion = models.CharField(max_length=60, blank=True, null=True)
    activo = models.BooleanField(default=True)
    imagen = models.ImageField(
        upload_to="productos/",
        blank=True,
        null=True,
    )

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

    # De qué ítem de compra viene este movimiento
    compra_item = models.ForeignKey(
        "CompraItem",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="movimientos",
    )

    venta_item = models.ForeignKey(
        "ventas.VentaItem",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
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
        

class Proveedor(models.Model):
    negocio = models.ForeignKey(Negocio, on_delete=models.PROTECT)
    nombre = models.CharField(max_length=120)
    contacto = models.CharField(max_length=120, blank=True, null=True)
    telefono = models.CharField(max_length=40, blank=True, null=True)
    correo = models.EmailField(blank=True, null=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "proveedor"

    def __str__(self):
        return self.nombre


class Compra(models.Model):
    DOC_FACTURA = "FACTURA"
    DOC_BOLETA = "BOLETA"
    DOC_GUIA = "GUIA"
    DOC_OTRO = "OTRO"

    DOC_CHOICES = [
        (DOC_FACTURA, "Factura"),
        (DOC_BOLETA, "Boleta"),
        (DOC_GUIA, "Guía de despacho"),
        (DOC_OTRO, "Otro"),
    ]
    negocio = models.ForeignKey(Negocio, on_delete=models.PROTECT)
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT)
    doc_tipo = models.CharField(max_length=20, choices=DOC_CHOICES)
    doc_num = models.CharField(max_length=40, blank=True, null=True)
    fecha = models.DateTimeField(auto_now_add=True)
    comentario = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        db_table = "ingreso_compra"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.doc_tipo} {self.doc_num or ''} - {self.proveedor.nombre}".strip()


class CompraItem(models.Model):
    compra = models.ForeignKey(
        Compra,
        on_delete=models.CASCADE,
        related_name="items",
    )
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField()
    costo_unit = models.PositiveIntegerField(
        help_text="Costo unitario en pesos chilenos"
    )

    class Meta:
        db_table = "ingreso_item"

    def __str__(self):
        return f"{self.cantidad} x {self.producto.nombre} en {self.compra}"

    def save(self, *args, **kwargs):
        es_nuevo = self.pk is None
        super().save(*args, **kwargs)

        if es_nuevo:
            # Solo al CREAR el item generamos el movimiento de ENTRADA
            MovimientoInventario.objects.create(
                producto=self.producto,
                tipo=MovimientoInventario.TIPO_ENTRADA,
                cantidad=self.cantidad,
                comentario=f"Compra #{self.compra.id} {self.compra.doc_tipo} {self.compra.doc_num or ''}".strip(),
                compra_item=self,
            )