# mysite/settings_tailscale.py
from .settings import *  # importa tudo do settings original

import os

_tailscale_host = os.getenv('TAILSCALE_HOST', '').strip()
_tailscale_tailnet = os.getenv('TAILSCALE_TAILNET', '').strip()
_tailscale_fqdn = os.getenv('TAILSCALE_FQDN', '').strip()
_tailscale_ip = os.getenv('TAILSCALE_IP', '').strip()

_tailscale_hosts = {
    host for host in (
        _tailscale_fqdn,
        _tailscale_host,
        (
            f"{_tailscale_host}.{_tailscale_tailnet}.ts.net"
            if _tailscale_host and _tailscale_tailnet and '.' not in _tailscale_host
            else ''
        ),
        _tailscale_ip,
    )
    if host
}

# Permite acessar via Tailscale (MagicDNS, FQDN ou IP) e localmente
ALLOWED_HOSTS = sorted(_tailscale_hosts) + ['127.0.0.1', 'localhost']

# Garante que requisições vindas do domínio Tailscale sejam aceitas no CSRF
if _tailscale_hosts:
    _csrf_hosts = []
    for host in _tailscale_hosts:
        scheme = 'https' if not host.replace('.', '').isdigit() else 'http'
        # adiciona ambos os esquemas caso esteja servindo via tailscale serve (http) ou funnel (https)
        _csrf_hosts.extend([f"http://{host}", f"https://{host}"])
    CSRF_TRUSTED_ORIGINS = list(dict.fromkeys(_csrf_hosts + [
        'http://127.0.0.1',
        'https://127.0.0.1',
    ]))

# Se quiser forçar sempre SQLite aqui (ou Postgres), descomente:
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }
