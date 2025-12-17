
import os
import django
import sys

# Configurar Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "siper_pirula.settings")
django.setup()

from django.contrib.auth.models import User
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes

print("--- DEBUG UID GENERATION ---")
for user in User.objects.all()[:5]:
    pk = user.pk
    pk_str = str(pk)
    pk_bytes = force_bytes(pk_str)
    uid = urlsafe_base64_encode(pk_bytes)
    print(f"User: {user.username:15} | PK: {pk!r:5} | PK_STR: {pk_str!r:5} | UID: {uid!r}")

print("-----------------------------")
