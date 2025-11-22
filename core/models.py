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
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    negocio = models.ForeignKey(Negocio, on_delete=models.PROTECT)

    class Meta:
        db_table = "perfil_usuario"

    def __str__(self):
        return f"{self.user.username} ({self.negocio.nombre})"
