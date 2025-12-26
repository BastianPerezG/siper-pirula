from pathlib import Path
import environ, os
from dotenv import load_dotenv
import pymysql
pymysql.install_as_MySQLdb()
# 1) BASE_DIR primero
BASE_DIR = Path(__file__).resolve().parent.parent

# 2) Cargar .env desde la raíz del proyecto (donde está manage.py)
env = environ.Env(DEBUG=(bool, True))
environ.Env.read_env(BASE_DIR / ".env")

# Cargar el .env desde la raíz del proyecto
load_dotenv(BASE_DIR / ".env")

# 3) Variables
DEBUG = env("DEBUG")
SECRET_KEY = env("SECRET_KEY")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["127.0.0.1","localhost"])

# Config regional
LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"

CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[]
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # nuestras apps:
    "core", "inventario", "pedidos", "ventas", "tienda","reportes",
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "siper_pirula.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],   # opcional, útil
    "APP_DIRS": True,
    "OPTIONS": {
        "context_processors": [
            "django.template.context_processors.debug",
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
            "inventario.context_processors.stock_critico_context",
        ],
    },
}]

WSGI_APPLICATION = "siper_pirula.wsgi.application"


# 4) Base de datos: SQLite para desarrollo local, MySQL para producción
# Si existe DB_HOST en el .env, usa MySQL; si no, usa SQLite
if os.environ.get("DB_HOST"):
    # PRODUCCIÓN: MySQL (PythonAnywhere)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env("DB_NAME"),
            "USER": env("DB_USER"),
            "PASSWORD": env("DB_PASSWORD"),
            "HOST": env("DB_HOST"),
            "PORT": env("DB_PORT", default="3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
            "CONN_MAX_AGE": 60,
        }
    }
else:
    # DESARROLLO LOCAL: SQLite
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# 5) Static/Media (útil para despliegue)
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]  # Para archivos static en desarrollo
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 6) Producción en PythonAnywhere (ajusta tu subdominio)
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=["https://*.pythonanywhere.com"]
)

# Datos Webpay
WEBPAY_COMMERCE_CODE = "597055555532"
WEBPAY_API_KEY = "579B532A7440BB0C9079DED94D31EA1615BACEB56610332264630D42D0A36B1C"

TRANSBANK_ENVIRONMENT = os.environ.get("TRANSBANK_ENVIRONMENT", "INTEGRATION")

# Configuración de Login
LOGIN_URL = "core:login_interno"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:login_interno"

# Configuración de Email (Brevo SMTP - antes Sendinblue)
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp-relay.brevo.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
# El remitente visible en los emails (diferente del login SMTP)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="El Gran Pirula <noreply@granpirula.cl>")

# URL del sitio (para emails)
SITE_URL = env("SITE_URL", default="http://127.0.0.1:8000")


# Configuración de Backup Automático
BACKUP_DIR = BASE_DIR / "backups"
BACKUP_RETENTION_DAYS = 30  # Días a retener backups (opciones: 15, 30, 60, 90)

# Configuración de AWS S3 para Backups (opcional)
# Las credenciales se leen desde variables de ambiente por seguridad
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_SESSION_TOKEN = os.environ.get("AWS_SESSION_TOKEN", "")  # Requerido para AWS Academy
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
AWS_BACKUP_BUCKET = os.environ.get("AWS_BACKUP_BUCKET", "")  # Nombre del bucket S3