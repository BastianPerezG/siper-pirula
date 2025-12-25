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

    def generar_numero_documento(self):
        """
        Genera automáticamente el número de documento basado en el tipo y negocio.
        Formato: BOL-0001, FACT-0001, etc.
        Solo genera número si el tipo no es SIN_DOC y no tiene número asignado.
        """
        if self.doc_tipo == self.DOC_SIN_DOC:
            return None
        
        if self.doc_num:
            # Si ya tiene número, no lo regeneramos
            return self.doc_num
        
        # Determinar el prefijo según el tipo
        if self.doc_tipo == self.DOC_BOLETA:
            prefijo = "BOL"
        elif self.doc_tipo == self.DOC_FACTURA:
            prefijo = "FACT"
        else:
            prefijo = "DOC"
        
        # Obtener todas las ventas de este tipo y negocio con números válidos
        ventas_con_numero = Venta.objects.filter(
            negocio=self.negocio,
            doc_tipo=self.doc_tipo
        ).exclude(
            doc_num__isnull=True
        ).exclude(
            doc_num=""
        ).values_list('doc_num', flat=True)
        
        # Buscar el número más alto
        ultimo_numero = 0
        for doc_num in ventas_con_numero:
            try:
                # Intentar extraer el número (ej: "BOL-0001" -> 1)
                if doc_num.startswith(prefijo + '-'):
                    partes = doc_num.split('-')
                    if len(partes) == 2:
                        numero = int(partes[1])
                        if numero > ultimo_numero:
                            ultimo_numero = numero
            except (ValueError, IndexError):
                # Si no tiene el formato esperado, ignorar
                continue
        
        # Generar el nuevo número
        nuevo_numero = ultimo_numero + 1
        return f"{prefijo}-{nuevo_numero:04d}"

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

        Maneja correctamente filas del formset sin producto.
        """
        super().clean()

        # Validar stock SOLO si hay producto y cantidad
        if self.producto_id and self.cantidad:
            # Ahora es seguro acceder a self.producto
            disponible = self.producto.stock_actual
            if self.cantidad > disponible:
                raise ValidationError({
                    "cantidad": (
                        f"No hay stock suficiente. Disponible: "
                        f"{disponible} unidades."
                    )
                })

        # (opcional) Validar rango del descuento
        if self.descuento_pct is not None:
            valor = float(self.descuento_pct)
            if valor < 0 or valor > 100:
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

class PagoVenta(models.Model):
    MET_EFECTIVO = "EFECTIVO"
    MET_DEBITO = "DEBITO"
    MET_CREDITO = "CREDITO"
    MET_TRANSFERENCIA = "TRANSFERENCIA"

    METODOS = (
        (MET_EFECTIVO, "Efectivo"),
        (MET_DEBITO, "Tarjeta débito"),
        (MET_CREDITO, "Tarjeta crédito"),
        (MET_TRANSFERENCIA, "Transferencia bancaria"),
    )

    # Estados del pago
    ESTADO_PENDIENTE = "PENDIENTE"
    ESTADO_COMPLETADO = "COMPLETADO"
    ESTADO_RECHAZADO = "RECHAZADO"
    ESTADO_ANULADO = "ANULADO"

    ESTADOS = (
        (ESTADO_PENDIENTE, "Pendiente"),
        (ESTADO_COMPLETADO, "Completado"),
        (ESTADO_RECHAZADO, "Rechazado"),
        (ESTADO_ANULADO, "Anulado"),
    )

    venta = models.ForeignKey(
        Venta,
        on_delete=models.CASCADE,
        related_name="pagos",
    )
    metodo = models.CharField(max_length=20, choices=METODOS)
    monto = models.PositiveIntegerField()
    
    # Estado del pago
    estado = models.CharField(
        max_length=15,
        choices=ESTADOS,
        default=ESTADO_COMPLETADO,
        help_text="Estado del pago. Pendiente para transferencias no confirmadas."
    )
    
    # Vuelto (solo para efectivo)
    vuelto = models.PositiveIntegerField(
        default=0,
        help_text="Vuelto entregado al cliente (solo para pagos en efectivo)"
    )
    
    # Campos para transferencia bancaria
    codigo_referencia = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Código o número de referencia de la transferencia"
    )
    banco = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Banco desde donde se realizó la transferencia"
    )
    cuenta_origen = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Número de cuenta desde donde se realizó la transferencia"
    )
    titular_transferencia = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Nombre del titular de la cuenta origen"
    )
    
    # Campos para tarjetas (integración futura)
    referencia_transaccion = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Referencia de transacción de la pasarela de pago"
    )
    token_tarjeta = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Token de la transacción (para auditoría, no almacenar datos sensibles)"
    )
    ultimos_digitos = models.CharField(
        max_length=4,
        blank=True,
        null=True,
        help_text="Últimos 4 dígitos de la tarjeta"
    )
    
    # Auditoría
    fecha_hora = models.DateTimeField(auto_now_add=True)
    usuario_registra = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pagos_registrados",
    )
    fecha_confirmacion = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Fecha en que se confirmó el pago (para transferencias)"
    )
    usuario_confirma = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pagos_confirmados",
        blank=True,
        null=True,
        help_text="Usuario que confirmó el pago"
    )
    observaciones = models.TextField(
        blank=True,
        null=True,
        help_text="Observaciones o notas sobre el pago"
    )

    class Meta:
        db_table = "pago_venta"
        ordering = ["-fecha_hora"]

    def __str__(self):
        estado_str = self.get_estado_display()
        return f"Pago {self.get_metodo_display()} ${self.monto} - {estado_str} (Venta #{self.venta_id})"
    
    def es_efectivo(self):
        """Retorna True si el método de pago es efectivo"""
        return self.metodo == self.MET_EFECTIVO
    
    def es_transferencia(self):
        """Retorna True si el método de pago es transferencia"""
        return self.metodo == self.MET_TRANSFERENCIA
    
    def es_tarjeta(self):
        """Retorna True si el método de pago es tarjeta (débito o crédito)"""
        return self.metodo in [self.MET_DEBITO, self.MET_CREDITO]
    
    def esta_pendiente(self):
        """Retorna True si el pago está pendiente de confirmación"""
        return self.estado == self.ESTADO_PENDIENTE
    
    def confirmar(self, usuario):
        """Confirma un pago pendiente (para transferencias)"""
        if self.estado != self.ESTADO_PENDIENTE:
            raise ValidationError("Solo se pueden confirmar pagos pendientes")
        
        self.estado = self.ESTADO_COMPLETADO
        self.fecha_confirmacion = timezone.now()
        self.usuario_confirma = usuario
        self.save(update_fields=["estado", "fecha_confirmacion", "usuario_confirma"])


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
        Ventas cerradas dentro del rango de este turno.
        Busca desde el cierre de la caja anterior para incluir ventas 'huérfanas' 
        realizadas entre turnos (ej. si se olvidó abrir caja).
        Solo incluye ventas CERRADA (pagadas).
        """
        start_time = self.fecha_apertura
        
        # Buscar la última caja cerrada antes de esta apertura
        last_caja = CajaTurno.objects.filter(
            negocio=self.negocio,
            estado=self.EST_CERRADA,
            fecha_cierre__lt=self.fecha_apertura
        ).order_by('-fecha_cierre').first()
        
        if last_caja:
            start_time = last_caja.fecha_cierre
            
        # Filtramos ventas desde ese momento
        # Usamos gt (greater than) para no solapar milisegundos exactos
        qs = Venta.objects.filter(
            negocio=self.negocio,
            fecha__gt=start_time,
            estado=Venta.EST_CERRADA  # Solo ventas completadas/pagadas
        )

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
    ROL_CHOICES = [
        ("CAJERO", "Cajero"),
        ("SUPERVISOR", "Supervisor"),
        ("ADMIN", "Administrador"),
    ]


class DescuentoReglaRol(models.Model):
    """
    Define el tope de descuento permitido por rol.
    Por ahora usaremos solo `max_pct_ticket` (descuento sobre el total de la venta).
    """
    rol = models.CharField(
        max_length=20,
        choices=PerfilUsuario.ROL_CHOICES,  # ajusta al nombre real de tu tuple
        unique=True,
    )
    max_pct_ticket = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Máximo % de descuento sobre el ticket que puede aplicar este rol.",
    )
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "descuento_regla_rol"

    def __str__(self):
        return f"Regla descuento rol {self.rol} (ticket {self.max_pct_ticket}%)"
    
    
class CodigoAutorizacionDescuento(models.Model):
    """
    Código tipo PIN que permite autorizar descuentos por encima del tope del cajero.
    El código está asociado a un usuario 'superior' (supervisor/admin).
    """
    codigo = models.CharField(max_length=20, unique=True)
    usuario_autorizador = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="codigos_descuento",
        null=True,     
        blank=True,  
    )
    max_pct_ticket = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Tope máximo de descuento total que autoriza este código.",
    )
    valido_hasta = models.DateTimeField(null=True, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "codigo_autorizacion_descuento"

    def __str__(self):
        return f"Código {self.codigo} ({self.usuario_autorizador})"

    def esta_vigente(self):
        if not self.activo:
            return False
        if self.valido_hasta and timezone.now() > self.valido_hasta:
            return False
        return True

    
class AuditoriaDescuento(models.Model):
    NIVEL_TICKET = "TICKET"
    NIVEL_ITEM = "ITEM"

    NIVELES = (
        (NIVEL_TICKET, "Descuento sobre ticket"),
        (NIVEL_ITEM, "Descuento sobre ítem"),
    )

    venta = models.ForeignKey(
        Venta,
        on_delete=models.CASCADE,
        related_name="auditorias_descuento",
        null=True,     
        blank=True,     
    )
    item = models.ForeignKey(
        "VentaItem",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="auditorias_descuento",
    )
    nivel = models.CharField(max_length=10, choices=NIVELES)

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

    motivo = models.TextField()
    porc_descuento = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    monto_descuento = models.PositiveIntegerField(default=0)

    codigo_usado = models.CharField(max_length=20, blank=True)
    fecha_hora = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auditoria_descuento"
        ordering = ["-fecha_hora"]

    def __str__(self):
        return f"Descuento {self.nivel} en venta #{self.venta_id}"
