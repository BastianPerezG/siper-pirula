from django.db import models
from django.conf import settings

# Modelo Core 

class Negocio(models.Model):
    nombre = models.CharField(max_length=120)
    rut = models.CharField(max_length=20, unique=True)
    direccion = models.CharField(max_length=200, blank=True, null=True)
    telefono = models.CharField(max_length=30, blank=True, null=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "negocio"

    def __str__(self):
        return self.nombre


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
