from django.db import models
from django.db.models import Sum, Case, When, IntegerField, F
from django.core.exceptions import ValidationError
from core.models import Negocio
from django.contrib.auth.models import User
from django.conf import settings
from django.contrib.auth  import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

# =======
from django.utils.text import slugify
from django.utils import timezone


# Modelo Inventario.

class Marca(models.Model):
    negocio = models.ForeignKey(Negocio, on_delete=models.PROTECT)
    nombre = models.CharField(max_length=120)
    imagen = models.ImageField(
        upload_to="marcas/",
        blank=True,
        null=True,
        help_text="Logo de la marca"
    )
    activo = models.BooleanField(default=True)
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "marca"
        ordering = ["nombre"]
        verbose_name = "Marca"
        verbose_name_plural = "Marcas"

    def __str__(self):
        return self.nombre


class Categoria(models.Model):
    negocio = models.ForeignKey(Negocio, on_delete=models.PROTECT)
    nombre = models.CharField(max_length=80)

    slug = models.SlugField(max_length=100, blank=True)
    imagen = models.ImageField(upload_to="categorias/", null=True, blank=True)

    activo = models.BooleanField(default=True)
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
    proveedor = models.ForeignKey("Proveedor", on_delete=models.PROTECT)
    sku = models.CharField(max_length=40, unique=True, blank=True, null=True)
    ean = models.CharField("Código de barras", max_length=40, unique=True)
    nombre = models.CharField(max_length=120)
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT)
    marca = models.ForeignKey(
        Marca,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="productos",
        help_text="Marca del producto"
    )
    precio = models.PositiveIntegerField(default=0, help_text="Precio de venta en pesos chilenos")
    costo = models.PositiveIntegerField(default=0, help_text="Costo en pesos chilenos")
    unidad_de_venta = models.CharField(max_length=120, blank=True, null=False)
    formato = models.CharField(max_length=120, blank=True, null=False)
    stock_min = models.IntegerField(default=0)
    ubicacion = models.CharField(max_length=60, blank=True, null=True)
    activo = models.BooleanField(default=True)
    contiene_alcohol = models.BooleanField(
        default=False,
        verbose_name="¿Contiene alcohol?"
    )
    imagen = models.ImageField(
        upload_to="productos/",
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "producto"

    def __str__(self):
        return f"{self.nombre} ({self.ean})"
    
    def save(self, *args, **kwargs):
        creando = self.pk is None
        # Primero guardamos normalmente
        super().save(*args, **kwargs)

        # Si es nuevo y aún no tiene SKU, lo generamos
        if creando and not self.sku:
            if self.categoria_id:
                prefijo = slugify(self.categoria.nombre)[:3].upper() or "SKU"
            else:
                prefijo = "SKU"
            # Ej: CER-00001, VIN-00023, etc.
            self.sku = f"{prefijo}-{self.pk:05d}"
            # Guardamos solo el campo sku para evitar bucle
            super().save(update_fields=["sku"])
    
    def clean(self):
        errors = {}
        if self.precio is not None and self.precio <= 0:
            errors["precio"] = "El precio de venta debe ser mayor que 0"
        if self.costo is not None and self.costo <= 0:
            errors["costo"] = "El costo unitario debe ser mayor que 0"
        if errors:
            raise ValidationError(errors)

    @property
    def stock_actual(self):
        resultado = self.movimientos.aggregate(
            total=Sum(
                Case(
                    When(
                        tipo__in=[
                            MovimientoInventario.TIPO_ENTRADA,
                            MovimientoInventario.TIPO_AJUSTE
                        ],
                        then=F("cantidad")
                    ),
                    When(
                        tipo__in=[
                            MovimientoInventario.TIPO_SALIDA,
                            MovimientoInventario.TIPO_MERMA,
                            MovimientoInventario.TIPO_RESERVA,
                            MovimientoInventario.TIPO_VENTA, 
                        ],
                        then=-F("cantidad")
                    ),
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
    TIPO_RESERVA = "RESERVA"
    TIPO_VENTA = "VENTA"

    TIPO_CHOICES = [
        (TIPO_ENTRADA, "Entrada (compra, devolución)"),
        (TIPO_SALIDA, "Salida (venta manual, uso interno)"),
        (TIPO_AJUSTE, "Ajuste (conteo inventario)"),
        (TIPO_MERMA, "Merma (rotura, pérdida)"),
        (TIPO_RESERVA, "Reserva por pedido"),
        (TIPO_VENTA, "Venta"),
    ]

    producto = models.ForeignKey(
        "Producto",
        on_delete=models.PROTECT,
        related_name="movimientos",
    )

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


    pedido_item = models.ForeignKey(
        "pedidos.PedidoItem",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="movimientos",
    )

    fecha = models.DateTimeField(auto_now_add=True)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    cantidad = models.PositiveIntegerField()
    comentario = models.CharField(max_length=200, blank=True, null=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="movimientos_inventario",
    )

    class Meta:
        db_table = "movimiento_inventario"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.tipo} {self.cantidad} de {self.producto.nombre} [{self.fecha}]"
    
    def clean(self):
        """
        Evita que un movimiento deje el stock en negativo.
        """
        super().clean()

        # Sólo tiene sentido validar si hay producto y cantidad
        if not self.producto_id or not self.cantidad:
            return

        tipos_salida = {
            self.TIPO_SALIDA,
            self.TIPO_MERMA,
            self.TIPO_RESERVA,
            self.TIPO_VENTA,
        }

        if self.tipo in tipos_salida:
            stock_actual = self.producto.stock_actual  # incluye TODOS los movs previos
            # Si el movimiento ya existe, restamos su propia cantidad anterior
            if self.pk:
                anterior = MovimientoInventario.objects.get(pk=self.pk)
                if anterior.producto_id == self.producto_id:
                    stock_actual -= anterior.cantidad

            if self.cantidad > stock_actual:
                raise ValidationError(
                    {"cantidad": f"No hay stock suficiente. Stock actual: {stock_actual}"}
                )
        

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
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="compras_registradas",
    )
    archivo = models.FileField(     
        upload_to="compras_docs/",
        null=True,
        blank=True,
        help_text="Sube la factura, boleta o respaldo de esta compra (PDF, imagen, etc.)",
    )
    class Meta:
        db_table = "ingreso_compra"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.doc_tipo} {self.doc_num or ''} - {self.proveedor.nombre}".strip()

    @property
    def total(self):
        """Calcula el total de la compra sumando todos los ítems."""
        return sum(item.subtotal for item in self.items.all())


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

    @property
    def subtotal(self):
        """Calcula el subtotal del ítem (cantidad * costo_unit)."""
        return self.cantidad * self.costo_unit

    def save(self, *args, **kwargs):
        es_nuevo = self.pk is None
        super().save(*args, **kwargs)

        if es_nuevo:
            # Solo al crear el item generamos el movimiento de ENTRADA
            MovimientoInventario.objects.create(
                producto=self.producto,
                tipo=MovimientoInventario.TIPO_ENTRADA,
                cantidad=self.cantidad,
                comentario=f"Compra #{self.compra.id} {self.compra.doc_tipo} {self.compra.doc_num or ''}".strip(
                ),
                compra_item=self,
            )


class PlantillaProveedorProducto(models.Model):
    """
    Modelo de relación que actúa como la 'Plantilla por Distribuidor'
    para almacenar los datos específicos de costo y unidad para un producto
    ofrecido por un proveedor particular.
    """
    # FKs a los modelos existentes
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE)
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)

    # Requerimientos de la Plantilla
    sku_proveedor = models.CharField(
        max_length=40,
        null=True,
        blank=True,
        verbose_name="SKU del Proveedor"
    )
    precio_costo = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Precio de Costo"
    )
    precio_sugerido = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Precio Sugerido"
    )
    unidad_venta = models.CharField(
        max_length=40,
        null=True,
        blank=True,
        verbose_name="Unidad de Venta (e.g., Pack, Caja, Botella)"
    )
    formato = models.CharField(
        max_length=40,
        null=True,
        blank=True,
        verbose_name="Formato/Volumen"
    )

    class Meta:
        verbose_name = "Plantilla Proveedor-Producto"
        verbose_name_plural = "Plantillas Proveedor-Producto"
        # Asegura que un proveedor solo pueda listar un producto una vez
        unique_together = ('proveedor', 'producto')

    def __str__(self):
        return f"{self.proveedor.nombre} - {self.producto.nombre}"
    # Propiedad para obtener la última fecha de compra para este par proveedor/producto
    @property
    def ultima_fecha_compra(self):
        return Compra.objects.filter(
            items__producto=self.producto,  # Filtra las compras del producto
            proveedor=self.proveedor       # Y que fueron a este proveedor
        ).order_by('-fecha').values_list('fecha', flat=True).first()

    # Propiedad para obtener la cantidad recibida en la última compra (historial)
    @property
    def ultima_cantidad_recibida(self):
        ultimo_item = CompraItem.objects.filter(
            compra__proveedor=self.proveedor,
            producto=self.producto
        ).order_by('-compra__fecha').first()
        return ultimo_item.cantidad if ultimo_item else 0
##############################




class Promo(models.Model):
    """
    Combo/pack de productos con precio especial.
    Ej: 'Pack Terremoto 18' = pipeño + granadina + helado de piña.
    """
    negocio = models.ForeignKey(Negocio, on_delete=models.PROTECT)

    nombre = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, blank=True)

    descripcion = models.TextField(blank=True, null=True)

    # Imagen representativa para la web
    imagen = models.ImageField(
        upload_to="promos/",
        blank=True,
        null=True,
    )

    # Precio que pagará el cliente por el combo
    precio_combo = models.PositiveIntegerField(
        help_text="Precio final del combo en pesos chilenos"
    )

    # Estado general
    activo = models.BooleanField(default=True)
    mostrar_en_portada = models.BooleanField(
        default=True,
        help_text="Si está marcado, se mostrará destacados en la tienda",
    )

    # Vigencia flexible
    fecha_inicio = models.DateField(blank=True, null=True)
    fecha_fin = models.DateField(blank=True, null=True)

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "promo"
        ordering = ["-activo", "nombre"]

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nombre)
        super().save(*args, **kwargs)

    # ----- Lógica de negocio -----

    @property
    def precio_normal(self) -> int:
        """
        Suma del precio normal de todos los productos del combo.
        """
        total = 0
        for item in self.items.select_related("producto"):
            total += (item.producto.precio or 0) * item.cantidad
        return total

    @property
    def precio_final(self) -> int:
        """
        Precio que usará el carrito.
        En este modelo, el precio final ES el precio del combo.
        """
        return self.precio_combo

    @property
    def ahorro(self) -> int:
        """
        Diferencia entre precio normal y precio combo.
        """
        return max(self.precio_normal - self.precio_combo, 0)

    @property
    def porcentaje_descuento(self) -> int:
        """
        Calcula el porcentaje de descuento redondeado.
        """
        if self.precio_normal > 0:
            return int((self.ahorro / self.precio_normal) * 100)
        return 0

    def tiene_stock(self, cantidad_packs: int = 1) -> bool:
        """
        Verifica si hay stock suficiente de todos los productos
        para vender 'cantidad_packs' combos.
        """
        for item in self.items.select_related("producto"):
            necesario = item.cantidad * cantidad_packs
            if item.producto.stock_actual < necesario:
                return False
        return True

    def descontar_stock(self, cantidad: int = 1, pedido=None):
        """
        Descuenta el stock de los productos incluidos en la promo.
        """
        from inventario.models import MovimientoInventario  # o el path correcto

        for item in self.items.select_related("producto"):
            total = item.cantidad * cantidad

            # tu lógica de movimiento de inventario
            MovimientoInventario.objects.create(
                producto=item.producto,
                tipo=MovimientoInventario.TIPO_VENTA,
                cantidad=total,
                comentario=f"Venta promo {self.nombre}",
                pedido=pedido,
            )

            # si además actualizas un campo directo de stock:
            item.producto.stock_disponible -= total
            item.producto.save(update_fields=["stock_disponible"])

    # ---------- NUEVO: vigencia de la promo ----------
    @property
    def esta_vigente(self) -> bool:
        """
        True si la promo está activa y la fecha actual está dentro
        del rango [fecha_inicio, fecha_fin] (cuando existan).
        """
        if not self.activo:
            return False

        hoy = timezone.now().date()

        if self.fecha_inicio and hoy < self.fecha_inicio:
            return False

        if self.fecha_fin and hoy > self.fecha_fin:
            return False

        return True

class PromoItem(models.Model):
    """
    Producto que forma parte de una promo/pack.
    """
    promo = models.ForeignKey(
        Promo,
        on_delete=models.CASCADE,
        related_name="items",
    )
    producto = models.ForeignKey(
        Producto,
        on_delete=models.PROTECT,
        related_name="promos_items",
    )
    cantidad = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "promo_item"
        unique_together = ("promo", "producto")

    def __str__(self):
        return f"{self.cantidad} x {self.producto.nombre} en {self.promo.nombre}"
