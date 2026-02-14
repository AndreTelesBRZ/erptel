from typing import Optional

from fastapi import Request


# Map hostname suffixes to loja_codigo to keep tenant resolution consistent.
HOST_LOJA_CODES = {
    "edsondosparafusos.app.br": "00001",
    "llfix.app.br": "00003",
}


def _clean_host(host: Optional[str]) -> Optional[str]:
    if not host:
        return None
    candidate = host.strip().lower()
    if ":" in candidate:
        candidate = candidate.split(":", 1)[0]
    if candidate.endswith("."):
        candidate = candidate.rstrip(".")
    return candidate or None


def resolve_loja_codigo_from_host(host: Optional[str], default: str) -> str:
    candidate = _clean_host(host)
    if not candidate:
        return default
    for suffix, code in HOST_LOJA_CODES.items():
        if candidate.endswith(suffix):
            return code
    return default


def determine_request_loja_codigo(request: Optional[Request], default: str) -> str:
    if not request:
        return default
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if not host and request.url:
        host = request.url.hostname
    return resolve_loja_codigo_from_host(host, default)
