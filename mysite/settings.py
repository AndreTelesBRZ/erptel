"""
Django settings for mysite project.
"""

import os
from pathlib import Path

import dj_database_url
from corsheaders.defaults import default_headers

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


# ======================================================
# BASE DIR
# ======================================================
BASE_DIR = Path(__file__).resolve().parent.parent


# ======================================================
# ENV (controlado pelo systemd)
# ======================================================
if load_dotenv:
    env_file = os.getenv("ENV_FILE")
    if env_file:
        load_dotenv(env_file)


# ======================================================
# TENANT / LOJA (após ENV carregado)
# ======================================================
TENANT = os.getenv("TENANT")
LOJA_CODIGO = os.getenv("LOJA_CODIGO")

VALID_TENANTS = {"EDSON", "LLFIX"}

if TENANT not in VALID_TENANTS:
    raise RuntimeError(
        f"TENANT inválido: {TENANT}. Use apenas {', '.join(VALID_TENANTS)}."
    )

if not LOJA_CODIGO:
    raise RuntimeError("LOJA_CODIGO não definido no ambiente.")


# ======================================================
# SECURITY
# ======================================================
SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-dev-only")


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


DEBUG = _env_bool("DEBUG", False)

ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("ALLOWED_HOSTS", "").split(",")
    if h.strip()
]

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

# 🔒 Cloudflare / Nginx / Gunicorn
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True


DATA_UPLOAD_MAX_NUMBER_FIELDS = int(
    os.getenv("DATA_UPLOAD_MAX_NUMBER_FIELDS", "20000")
)


# ======================================================
# LOGIN / LOGOUT
# ======================================================
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "login"


# ======================================================
# APPLICATIONS
# ======================================================
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",

    "corsheaders",
    "rest_framework",
    "rest_framework.authtoken",
    "django_filters",

    "core",
    "products",
    "clients",
    "sales",
    "companies",
    "purchases",
    "finance",
    "relatorios",
    "estoque",
    "custos",
    "api",
]


# ======================================================
# MIDDLEWARE
# ======================================================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",

    # Middleware corporativo
    "core.middleware.ActiveCompanyMiddleware",

    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# ======================================================
# URLS / TEMPLATES
# ======================================================
ROOT_URLCONF = "mysite.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.active_company",
                "core.context_processors.user_profile",
            ],
        },
    },
]

WSGI_APPLICATION = "mysite.wsgi.application"


# ======================================================
# DATABASE (ERP = fonte da verdade)
# ======================================================
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "Configuração PostgreSQL ausente: defina DATABASE_URL no ambiente."
    )

DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=600,
        ssl_require=False,
    )
}

# 🔒 Trava de segurança por TENANT
EXPECTED_DB_BY_TENANT = {
    "EDSON": "erptel",
    "LLFIX": "erpllfix",
}

expected_db = EXPECTED_DB_BY_TENANT.get(TENANT)

if expected_db and DATABASES["default"]["NAME"] != expected_db:
    raise RuntimeError(
        f"Banco incorreto em uso: {DATABASES['default']['NAME']} "
        f"(esperado: {expected_db}, tenant: {TENANT})"
    )


# ======================================================
# AUTHENTICATION
# ======================================================
AUTHENTICATION_BACKENDS = [
    "core.auth_backends.ERPAuthBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = []


# ======================================================
# DJANGO REST FRAMEWORK
# ======================================================
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
}


# ======================================================
# CORS / INTEGRAÇÃO
# ======================================================
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_HEADERS = list(default_headers) + ["x-app-token"]

APP_INTEGRATION_TOKEN = os.getenv("APP_INTEGRATION_TOKEN", "")


# ======================================================
# INTERNATIONALIZATION
# ======================================================
LANGUAGE_CODE = "pt-br"
TIME_ZONE = os.getenv("TIME_ZONE", "America/Sao_Paulo")
USE_I18N = True
USE_TZ = True

LOCALE_PATHS = [BASE_DIR / "locale"]


# ======================================================
# STATIC / MEDIA
# ======================================================
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ======================================================
# EMAIL
# ======================================================
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    "ERP <no-reply@example.com>"
)


# ======================================================
# DEFAULT PK
# ======================================================
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
