from pathlib import Path
import environ, os

# 1) BASE_DIR primero
BASE_DIR = Path(__file__).resolve().parent.parent

# 2) Cargar .env desde la raíz del proyecto (donde está manage.py)
env = environ.Env(DEBUG=(bool, True))
environ.Env.read_env(BASE_DIR / ".env")

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
    # tus apps:
    "core", "inventario", "pedidos", "ventas",
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
        ],
    },
}]

WSGI_APPLICATION = "siper_pirula.wsgi.application"


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
# 4) DB: MySQL via mysqlclient (usa variables del .env)
#DATABASES = {
    #"default": {
        #"ENGINE": "django.db.backends.mysql",
        #"NAME": env("DB_NAME"),
        #"USER": env("DB_USER"),
        #"PASSWORD": env("DB_PASSWORD"),
        #"HOST": env("DB_HOST", default="127.0.0.1"),
        #"PORT": env("DB_PORT", default="3306"),
        #"OPTIONS": {
                #"charset": "utf8mb4",
                # en Windows a veces ayuda:
                # "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            #},
            #"CONN_MAX_AGE": 60,   # pooling básico (60 s)
        #}
        
#}

# 5) Static/Media (útil para despliegue)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"          # collectstatic en producción
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 6) Producción en PythonAnywhere (ajusta tu subdominio)
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=["https://*.pythonanywhere.com"]
)
