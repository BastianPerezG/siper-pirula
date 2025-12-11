from django.db import models
from django.contrib.auth import get_user_model
from django.conf import settings

# Modelo Core 

class Negocio(models.Model):
    nombre = models.CharField(max_length=120)
    rut = models.CharField(max_length=20, unique=True)
    direccion = models.CharField(max_length=200, blank=True, null=True)
    telefono = models.CharField(max_length=30, blank=True, null=True)
    activo = models.BooleanField(default=True)
    
    # Datos bancarios para transferencias
    banco_nombre = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Nombre del banco (ej: Banco de Chile, Banco Estado, etc.)"
    )
    banco_tipo_cuenta = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Tipo de cuenta (ej: Corriente, Vista, Ahorro)"
    )
    banco_numero_cuenta = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Número de cuenta bancaria"
    )
    banco_rut_titular = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="RUT del titular de la cuenta"
    )
    banco_nombre_titular = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Nombre del titular de la cuenta"
    )
    banco_email = models.EmailField(
        blank=True,
        null=True,
        help_text="Email para notificaciones de transferencias (opcional)"
    )

    class Meta:
        db_table = "negocio"

    def __str__(self):
        return self.nombre
    
    def tiene_datos_bancarios(self):
        """Verifica si el negocio tiene datos bancarios configurados"""
        return bool(
            self.banco_nombre and
            self.banco_numero_cuenta and
            self.banco_rut_titular
        )


class PerfilUsuario(models.Model):
   
    ROL_CAJERO = "CAJERO"
    ROL_MESON = "MESON"
    ROL_ADMIN = "ADMIN"

    ROL_CHOICES = [
        (ROL_CAJERO, "Cajero"),
        (ROL_MESON, "Mesón"),
        (ROL_ADMIN, "Administrador"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    negocio = models.ForeignKey(Negocio, on_delete=models.PROTECT)

    rol = models.CharField(
        max_length=20,
        choices=ROL_CHOICES,
        default=ROL_MESON,
        help_text="Rol del usuario dentro del sistema SIPER-Pirula.",
    )

    activo = models.BooleanField(
        default=True,
        help_text="Si está desactivado, no puede iniciar sesión en el sistema interno.",
    )

    telefono = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        help_text="Teléfono de contacto del trabajador.",
    )

    class Meta:
        db_table = "perfil_usuario"

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.negocio.nombre})"

    @property
    def es_admin(self):
        return self.rol == self.ROL_ADMIN

    @property
    def es_cajero(self):
        return self.rol == self.ROL_CAJERO

    @property
    def es_meson(self):
        return self.rol == self.ROL_MESON

User = get_user_model()

class BitacoraAccion(models.Model):
    """Modelo para registrar automáticamente todas las acciones relevantes de los usuarios."""
    fecha_hora = models.DateTimeField(
        auto_now_add = True,
        verbose_name= "Fecha y Hora"
    )
    usuario = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL,
        null=True, 
        verbose_name= "Usuario"     
    )
    accion = models.CharField(
        max_length=150,
        verbose_name="Tipo de Acción"
    )
    entidad_id = models.CharField(
        max_length=50,
        verbose_name="ID de monitor."
    )
    detalles = models.JSONField(
        default=dict,
        verbose_name="Detalles en Json"
    )
    class Meta:
        verbose_name = "Registro de Bitácora Simple"
        verbose_name_plural = "Bitácora de Acciones Simples"
        ordering = ['-fecha_hora']
    def __str__(self):
        return f"[{self.fecha_hora.strftime('%Y-%m-%d %H:%M')}] {self.accion} por {self.usuario}" 
       