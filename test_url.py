
import os
import django
import sys

# Configurar Django
try:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "siper_pirula.settings")
    django.setup()
except Exception as e:
    print(f"Error setup django: {e}")
    sys.exit(1)

from django.urls import reverse
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.models import User

print("\n--- TEST DE GENERACIÓN DE URL ---")

# Buscar usuario de prueba
email_target = "scastrof2@outlook.com"
user = User.objects.filter(email=email_target).first()

if not user:
    print(f"Usuario {email_target} no encontrado. Usando el primero disponible.")
    user = User.objects.first()

if not user:
    print("No hay usuarios en la BD.")
    sys.exit(1)

print(f"User encontrado: {user.username} (ID: {user.pk})")

# 1. Generar tokens
try:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    print(f"Generado UID: '{uid}' (Tipo: {type(uid)})")
    print(f"Generado Token: '{token}' (Tipo: {type(token)})")
except Exception as e:
    print(f"Error generando tokens: {e}")
    sys.exit(1)

# 2. Probar Reverse
try:
    print("Intentando reverse('password_reset_confirm')...")
    path = reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
    print(f"✅ ÉXITO! URL generada: {path}")
except Exception as e:
    print(f"❌ FALLÓ reverse: {e}")

print("---------------------------------")
