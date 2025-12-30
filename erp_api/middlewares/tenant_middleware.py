import os
import jwt
import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from urllib.parse import urlparse

logger = logging.getLogger("erp_api.tenant")

APP_INTEGRATION_TOKEN = (os.getenv("APP_INTEGRATION_TOKEN") or "").strip()
JWT_SECRET = os.getenv("JWT_SECRET", "change-me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
APP_TENANT = (os.getenv("APP_TENANT") or "").strip()
LOJA_CODIGO = (os.getenv("LOJA_CODIGO") or "").strip()
APP_DOMAIN = (
    os.getenv("APP_DOMAIN")
    or os.getenv("API_TENANT_DOMAIN")
    or os.getenv("APP_TENANT_DOMAIN")
    or ""
)


def _extract_domain(value: str | None) -> str:
    if not value:
        return ""
    trimmed = value.strip()
    if not trimmed:
        return ""
    if "://" in trimmed:
        parsed = urlparse(trimmed)
        host = parsed.hostname or ""
    else:
        host = trimmed
    host = host.split(",")[0].split(":")[0].lower().strip()
    return host


def _extract_domains(value: str | None) -> list[str]:
    if not value:
        return []
    items = [item.strip() for item in value.split(",") if item.strip()]
    domains = [_extract_domain(item) for item in items]
    return [domain for domain in domains if domain]


def _normalize_loja(value: str | None) -> str:
    if value is None:
        return ""
    trimmed = value.strip()
    if not trimmed:
        return ""
    normalized = trimmed.lstrip("0")
    return normalized or "0"


def _token_matches_app_token(request: Request) -> bool:
    app_token = (request.headers.get("x-app-token") or "").strip()
    if not APP_INTEGRATION_TOKEN:
        return True
    if app_token == APP_INTEGRATION_TOKEN:
        return True
    auth_header = (request.headers.get("authorization") or "").strip()
    if not auth_header:
        return False
    scheme, _, raw_value = auth_header.partition(" ")
    if scheme.lower() in ("bearer", "token", "app") and raw_value.strip() == APP_INTEGRATION_TOKEN:
        return True
    return False


def _token_is_valid_jwt(request: Request) -> bool:
    raw_token = ""
    auth_header = (request.headers.get("authorization") or "").strip()
    if auth_header:
        scheme, _, raw_value = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not raw_value.strip():
            return False
        raw_token = raw_value.strip()
    else:
        raw_token = (request.headers.get("x-app-token") or "").strip()
        if not raw_token:
            return False
    try:
        jwt.decode(raw_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return False
    except jwt.InvalidTokenError:
        return False
    return True


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        host = request.headers.get("host")
        forwarded_host = request.headers.get("x-forwarded-host")
        origin = request.headers.get("origin") or request.headers.get("referer")
        host_domain = _extract_domain(host)
        forwarded_domain = _extract_domain(forwarded_host)
        origin_domain = _extract_domain(origin)
        request_domain = host_domain or forwarded_domain or origin_domain

        if not APP_TENANT:
            return JSONResponse(
                status_code=500,
                content={"message": "APP_TENANT não configurado para esta instância"},
            )

        expected_domains = _extract_domains(APP_DOMAIN)
        if expected_domains and not request_domain:
            return JSONResponse(status_code=400, content={"message": "Host header ausente"})

        loja_from_domain = None
        if request_domain:
            pool = getattr(request.app.state, "data_pool", None)
            if pool:
                try:
                    async with pool.acquire() as conn:
                        row = await conn.fetchrow(
                            """
                            SELECT loja_codigo
                            FROM dominios_lojas
                            WHERE dominio = $1 AND ativo = TRUE
                            LIMIT 1
                            """,
                            request_domain,
                        )
                    if row:
                        loja_from_domain = row["loja_codigo"]
                except Exception:
                    logger.exception("Falha ao resolver loja pelo domínio %s", request_domain)

        if expected_domains and request_domain and request_domain not in expected_domains:
            if not loja_from_domain:
                blocked = request_domain or "desconhecido"
                return JSONResponse(
                    status_code=403,
                    content={"message": f"Domínio não autorizado: {blocked}"},
                )

        loja_codigo = loja_from_domain or LOJA_CODIGO
        if not loja_codigo:
            return JSONResponse(
                status_code=500,
                content={"message": "LOJA_CODIGO não configurado para esta instância"},
            )

        request.state.loja_codigo = loja_codigo
        return await call_next(request)
