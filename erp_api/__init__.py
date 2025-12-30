from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Body, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, field_validator, ValidationError, ConfigDict
from typing import List, Optional
import asyncpg
import os
import base64
import hashlib
import secrets
import hmac
import jwt
import django
import re
from decimal import Decimal
from datetime import datetime, timedelta, timezone as dt_timezone
from django.utils import timezone as dj_timezone
from erp_api.clientes import router as clientes_router
import logging
from pathlib import Path
from erp_api.middlewares.tenant_middleware import TenantMiddleware

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent.parent
if load_dotenv:
    load_dotenv(BASE_DIR / ".env")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")
django.setup()

from clients.models import Client, ClienteSync
from products.models import Product, ProdutoSync
from api.models import PlanoPagamentoCliente, Loja
from sales.models import Pedido, ItemPedido
from django.db import transaction, models, connection
from django.core.files.uploadedfile import SimpleUploadedFile
from core.forms import SefazConfigurationForm
from core.models import SefazConfiguration
from companies.models import Company
from companies.services import (
    prepare_company_nfe_query,
    serialize_nfe_document,
    has_configured_sefaz_certificate,
)

logger = logging.getLogger("erp_api")
# File logger to capture API issues even when journald is unavailable
if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
    log_file = Path(__file__).resolve().parent / "erp_api_debug.log"
    handler = logging.FileHandler(log_file)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)

app = FastAPI(
    title=os.getenv("APP_NAME", "API Force"),
    servers=[{"url": os.getenv("PUBLIC_API_URL", "")}],
)
bearer_scheme = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/api")
images_router = APIRouter(prefix="/api/imagens", tags=["imagens"])
auth_router = APIRouter(prefix="/auth", tags=["auth"])


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


def _env_csv(name: str) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


ENVIRONMENT = (os.getenv("ENVIRONMENT") or "").strip().lower()
if not ENVIRONMENT:
    ENVIRONMENT = "development" if _env_bool("DEBUG", True) else "production"

DEFAULT_API_ALLOWED_HOSTS = {
    "apiforce.edsondosparafusos.app.br",
    "apiforce.llfix.app.br",
}
API_ALLOWED_HOSTS = {host.lower() for host in DEFAULT_API_ALLOWED_HOSTS}
api_extra_hosts = _env_csv("API_ALLOWED_HOSTS")
if api_extra_hosts:
    API_ALLOWED_HOSTS.update(host.lower() for host in api_extra_hosts)

allow_internal_hosts = _env_bool(
    "ALLOW_INTERNAL_HOSTS",
    _env_bool("DEBUG", False) or ENVIRONMENT in ("dev", "development", "local"),
)
if allow_internal_hosts:
    API_ALLOWED_HOSTS.update({"10.0.0.78", "127.0.0.1", "localhost"})

DEFAULT_CORS_ALLOWED_ORIGINS = [
    "https://vendas.edsondosparafusos.app.br",
    "https://vendas.llfix.app.br",
    "https://apiforce.edsondosparafusos.app.br",
    "https://apiforce.llfix.app.br",
    "https://app.llfix.com.br",
]
DEV_EXTRA_CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "https://2pn9n2auqsujhe5pkhjl35odhar6ieddxpge24zk940sjgp3xb-h845251650.scf.usercontent.goog",
]

env_origins = _env_csv("CORS_ALLOWED_ORIGINS")
if env_origins:
    CORS_ALLOWED_ORIGINS = env_origins
else:
    if ENVIRONMENT in ("dev", "development", "local"):
        CORS_ALLOWED_ORIGINS = DEFAULT_CORS_ALLOWED_ORIGINS + DEV_EXTRA_CORS_ALLOWED_ORIGINS
    else:
        CORS_ALLOWED_ORIGINS = DEFAULT_CORS_ALLOWED_ORIGINS
    CORS_ALLOWED_ORIGINS = list(dict.fromkeys(CORS_ALLOWED_ORIGINS))

env_origin_regex = (os.getenv("CORS_ALLOWED_ORIGIN_REGEX") or "").strip()
if env_origin_regex:
    CORS_ALLOWED_ORIGIN_REGEX = env_origin_regex
elif ENVIRONMENT in ("dev", "development", "local"):
    CORS_ALLOWED_ORIGIN_REGEX = r"^https://.*\.scf\.usercontent\.goog$"
else:
    CORS_ALLOWED_ORIGIN_REGEX = ""

app.add_middleware(TenantMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(API_ALLOWED_HOSTS))
cors_kwargs = {
    "allow_origins": CORS_ALLOWED_ORIGINS,
    "allow_credentials": True,
    "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    "allow_headers": [
        "Authorization",
        "Accept",
        "Content-Type",
        "X-App-Token",
        "X-Loja-Codigo",
        "X-Forwarded-Host",
        "X-Forwarded-Proto",
        "X-Requested-With",
    ],
}
if CORS_ALLOWED_ORIGIN_REGEX:
    cors_kwargs["allow_origin_regex"] = CORS_ALLOWED_ORIGIN_REGEX
app.add_middleware(CORSMiddleware, **cors_kwargs)


def validate_host(request: Request) -> None:
    host = request.headers.get("host")
    if not host:
        raise HTTPException(status_code=403, detail="Host ausente")
    hostname = host.split(":", 1)[0].lower().strip()
    if hostname not in API_ALLOWED_HOSTS:
        raise HTTPException(status_code=403, detail=f"Domínio não autorizado: {hostname}")


@app.middleware("http")
async def host_validation_middleware(request: Request, call_next):
    validate_host(request)
    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    content = detail if isinstance(detail, dict) else {"message": detail}
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled API error", exc_info=exc)
    return JSONResponse(status_code=500, content={"message": "erro interno"})

# -----------------------------------
# Conexões com PostgreSQL (dados vs. autenticação)
# -----------------------------------
DATA_DB_CONFIG = {
    "host": os.getenv("DATA_POSTGRES_HOST") or os.getenv("POSTGRES_HOST") or os.getenv("PGHOST", "127.0.0.1"),
    "database": os.getenv("DATA_POSTGRES_DB") or os.getenv("POSTGRES_DB") or os.getenv("PGDATABASE", "erptel"),
    "user": os.getenv("DATA_POSTGRES_USER") or os.getenv("POSTGRES_USER") or os.getenv("PGUSER", "postgres"),
    "password": os.getenv("DATA_POSTGRES_PASSWORD") or os.getenv("POSTGRES_PASSWORD") or os.getenv("PGPASSWORD", "minhasenha"),
    "port": int(os.getenv("DATA_POSTGRES_PORT") or os.getenv("POSTGRES_PORT") or os.getenv("PGPORT") or 5432),
}
AUTH_DB_CONFIG = {
    "host": os.getenv("AUTH_POSTGRES_HOST") or os.getenv("POSTGRES_HOST") or os.getenv("PGHOST", "127.0.0.1"),
    "database": os.getenv("AUTH_POSTGRES_DB") or os.getenv("POSTGRES_DB") or os.getenv("PGDATABASE", "erptel"),
    "user": os.getenv("AUTH_POSTGRES_USER") or os.getenv("POSTGRES_USER") or os.getenv("PGUSER", "postgres"),
    "password": os.getenv("AUTH_POSTGRES_PASSWORD") or os.getenv("POSTGRES_PASSWORD") or os.getenv("PGPASSWORD", "minhasenha"),
    "port": int(os.getenv("AUTH_POSTGRES_PORT") or os.getenv("POSTGRES_PORT") or os.getenv("PGPORT") or 5432),
}
POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN", "1"))
POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX", "10"))
POOL_COMMAND_TIMEOUT = float(os.getenv("DB_COMMAND_TIMEOUT", "10"))
DISABLE_API_AUTH = os.getenv("DISABLE_API_AUTH", "true").lower() in ("1", "true", "yes", "on")
JWT_SECRET = os.getenv("JWT_SECRET", "change-me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRES_MINUTES = int(os.getenv("JWT_EXPIRES_MINUTES", "60"))
DEFAULT_ADMIN_USER = os.getenv("DEFAULT_ADMIN_USER")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD")
APP_INTEGRATION_TOKEN = (os.getenv("APP_INTEGRATION_TOKEN") or "").strip()
PEDIDO_STATUS_VALUES = {
    "orcamento",
    "pre_venda",
    "em_separacao",
    "faturado",
    "entregue",
    "cancelado",
}
PAGAMENTO_STATUS_VALUES = {"aguardando", "pago_avista", "fatura_a_vencer", "negado"}
FRETE_MODALIDADE_VALUES = {"cif", "fob", "sem_frete"}
IMAGE_TYPE_PREFIXES = {
    "produto": "produtos",
    "subgrupo": "subgrupos",
    "marca": "marcas",
}
S3_BASE_URL = "https://s3.edsondosparafusos.app.br"
BASE_API_URL = (os.getenv("BASE_API_URL") or "").rstrip("/")
MINIO_ROOT_PREFIX = "produtos"
PLACEHOLDER_KEY = f"{MINIO_ROOT_PREFIX}/placeholders/sem-imagem.webp"
DISABLE_IMAGE_UPLOAD = os.getenv("DISABLE_IMAGE_UPLOAD", "true").lower() in ("1", "true", "yes", "on")
CLIENTES_LOJA_GLOBAL_CODE = (os.getenv("CLIENTES_LOJA_GLOBAL_CODE") or "00000").strip() or "00000"


@app.on_event("startup")
async def startup():
    app.state.data_pool = await asyncpg.create_pool(
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
        command_timeout=POOL_COMMAND_TIMEOUT,
        **DATA_DB_CONFIG,
    )
    app.state.auth_pool = await asyncpg.create_pool(
        min_size=1,
        max_size=max(POOL_MAX_SIZE // 2, 2),
        command_timeout=POOL_COMMAND_TIMEOUT,
        **AUTH_DB_CONFIG,
    )
    async with app.state.data_pool.acquire() as conn:
        await _ensure_tenant_tables(conn)
    async with app.state.auth_pool.acquire() as conn:
        await _ensure_auth_tables(conn)
        await _bootstrap_admin_user(conn)


@app.on_event("shutdown")
async def shutdown():
    for pool_attr in ("data_pool", "auth_pool"):
        pool = getattr(app.state, pool_attr, None)
        if pool:
            await pool.close()


def _get_data_pool():
    pool = getattr(app.state, "data_pool", None)
    if not pool:
        raise HTTPException(503, "Pool de dados não inicializado")
    return pool


def _get_auth_pool():
    pool = getattr(app.state, "auth_pool", None)
    if not pool:
        raise HTTPException(503, "Pool de autenticação não inicializado")
    return pool


def require_tenant(request: Request) -> str:
    loja_codigo = getattr(request.state, "loja_codigo", None)
    if not loja_codigo:
        raise HTTPException(500, "Loja não resolvida")
    return loja_codigo


def _normalize_loja_codigo(value: Optional[str]) -> str:
    if value is None:
        return ""
    trimmed = value.strip()
    if not trimmed:
        return ""
    normalized = trimmed.lstrip("0")
    return normalized or "0"


def _normalize_vendor_code(value: Optional[str]) -> str:
    if value is None:
        return ""
    trimmed = value.strip()
    if not trimmed:
        return ""
    digits = "".join(ch for ch in trimmed if ch.isdigit())
    if digits:
        return digits.lstrip("0") or "0"
    return trimmed.lower()


def _loja_matches(requested: Optional[str], tenant: Optional[str]) -> bool:
    if not requested or not tenant:
        return False
    return _normalize_loja_codigo(requested) == _normalize_loja_codigo(tenant)


def _loja_regex(loja_codigo: str) -> str:
    normalized = _normalize_loja_codigo(loja_codigo)
    if not normalized:
        return r"^$"
    escaped = re.escape(normalized)
    return rf"^0*{escaped}$"


def _sql_loja_equals(column_name: str, param_index: int) -> str:
    return f"ltrim({column_name}, '0') = ltrim(${param_index}, '0')"


def _sql_vendor_equals(column_name: str, param_index: int) -> str:
    return f"ltrim({column_name}, '0') = ltrim(${param_index}, '0')"


def _sql_loja_equals_or_global(column_name: str, param_index: int) -> str:
    if not CLIENTES_LOJA_GLOBAL_CODE:
        return _sql_loja_equals(column_name, param_index)
    return f"({_sql_loja_equals(column_name, param_index)} OR {column_name} = '{CLIENTES_LOJA_GLOBAL_CODE}')"


async def _ensure_tenant_tables(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dominios_lojas (
            id SERIAL PRIMARY KEY,
            dominio VARCHAR(255) UNIQUE NOT NULL,
            loja_codigo VARCHAR(10) NOT NULL,
            ativo BOOLEAN DEFAULT TRUE
        );
        INSERT INTO dominios_lojas (dominio, loja_codigo)
        VALUES
            ('vendas.llfix.app.br', '000003'),
            ('vendas.edsondosparafusos.app.br', '00001'),
            ('apiforce.llfix.app.br', '000003'),
            ('apiforce.edsondosparafusos.app.br', '00001')
        ON CONFLICT (dominio) DO NOTHING;
        UPDATE dominios_lojas
        SET loja_codigo = '000003'
        WHERE dominio = 'vendas.llfix.app.br'
          AND loja_codigo <> '000003';
        UPDATE dominios_lojas
        SET loja_codigo = '000003'
        WHERE dominio = 'apiforce.llfix.app.br'
          AND loja_codigo <> '000003';
        UPDATE dominios_lojas
        SET loja_codigo = '00001'
        WHERE dominio = 'apiforce.edsondosparafusos.app.br'
          AND loja_codigo <> '00001';
        """
    )


def _build_image_key(tipo: str, codigo: str) -> str:
    prefix = IMAGE_TYPE_PREFIXES.get(tipo)
    if not prefix:
        raise HTTPException(400, "Tipo inválido. Use: produto, subgrupo ou marca.")
    if not codigo:
        raise HTTPException(400, "Código não informado.")
    return f"{MINIO_ROOT_PREFIX}/{prefix}/{codigo}.webp"


def _public_image_url(key: str) -> str:
    return f"{S3_BASE_URL}/{key}"


def _image_api_url(tipo: str, codigo: str) -> str:
    base = BASE_API_URL
    if base:
        return f"{base}/api/imagens/{tipo}/{codigo}"
    return f"/api/imagens/{tipo}/{codigo}"


def _produto_base_sql() -> str:
    return """
        SELECT
            p.produto_codigo AS codigo,
            p.descricao_completa,
            p.referencia,
            p.secao,
            p.grupo,
            p.subgrupo,
            p.unidade,
            p.ean,
            p.plu,
            pr.preco_normal,
            pr.preco_promocao1,
            pr.preco_promocao2,
            pe.estoque_disponivel,
            pr.loja_codigo AS loja,
            p.refplu,
            p.row_hash,
            pr.custo,
            pr.updated_at AS preco_updated_at,
            v.codigo_imagem,
            v.tipo_imagem
        FROM erp_produtos p
        JOIN erp_produtos_precos pr
            ON pr.produto_codigo = p.produto_codigo
        LEFT JOIN erp_produtos_estoque pe
            ON pe.produto_codigo = p.produto_codigo
           AND pe.loja_codigo = pr.loja_codigo
        LEFT JOIN vw_produto_imagem v
            ON v.produto_codigo = p.produto_codigo
           AND v.loja_codigo = pr.loja_codigo
    """


def _produto_sync_base_sql() -> str:
    return """
        SELECT
            p.codigo AS codigo,
            p.descricao_completa,
            p.referencia,
            p.secao,
            p.grupo,
            p.subgrupo,
            p.unidade,
            p.ean,
            p.plu,
            p.preco_normal,
            p.preco_promocao1,
            p.preco_promocao2,
            p.estoque_disponivel,
            p.loja,
            p.refplu,
            p.row_hash,
            NULL::numeric AS custo,
            NULL::varchar AS codigo_imagem,
            NULL::varchar AS tipo_imagem
        FROM erp_produtos_sync p
    """


def build_product_image_payload(
    codigo_imagem: Optional[str],
    tipo_imagem: Optional[str],
) -> dict:
    codigo = str(codigo_imagem).strip() if codigo_imagem is not None else ""
    tipo = str(tipo_imagem).strip() if tipo_imagem is not None else ""
    if codigo and tipo:
        imagem_url = _image_api_url(tipo, codigo)
    else:
        imagem_url = _image_api_url("default", "sem-imagem")
    return {
        "codigo_imagem": codigo_imagem,
        "tipo_imagem": tipo_imagem,
        "imagem_url": imagem_url,
    }


def _normalize_product_payload(data: dict) -> dict:
    payload = dict(data)
    codigo = payload.get("codigo")
    payload.setdefault("id", codigo)
    unidade = payload.get("unidade")
    if unidade and "sigla_unidade" not in payload:
        payload["sigla_unidade"] = unidade
    if "estoque_minimo" not in payload:
        payload["estoque_minimo"] = payload.get("min_stock") or 0
    return payload


def _serialize_sefaz_config(config: SefazConfiguration) -> dict:
    return {
        "base_url": config.base_url,
        "token": config.token,
        "timeout": config.timeout,
        "environment": config.environment,
        "certificate": {
            "is_configured": has_configured_sefaz_certificate(config),
            "subject": config.certificate_subject,
            "serial_number": config.certificate_serial_number,
            "valid_from": config.certificate_valid_from.isoformat() if config.certificate_valid_from else None,
            "valid_until": config.certificate_valid_until.isoformat() if config.certificate_valid_until else None,
            "uploaded_at": config.certificate_uploaded_at.isoformat() if config.certificate_uploaded_at else None,
        },
    }


def _plan_to_dict(plan: PlanoPagamentoCliente) -> dict:
    return {
        "CLICOD": plan.cliente_codigo,
        "PLACOD": plan.plano_codigo,
        "PLADES": plan.plano_descricao or "",
        "PLAENT": Decimal("0"),
        "PLAINTPRI": plan.dias_primeira_parcela,
        "PLAINTPAR": plan.dias_entre_parcelas,
        "PLANUMPAR": plan.parcelas,
        "PLAVLRMIN": plan.valor_minimo,
        "PLAVLRACR": plan.valor_acrescimo,
    }

def _fetch_planos_pagamento(cliente_codigo: str, loja_codigo: str) -> list[PlanoPagamentoCliente]:
    qs = PlanoPagamentoCliente.objects.filter(
        cliente_codigo=cliente_codigo,
        loja_codigo=loja_codigo,
    ).order_by("plano_codigo")
    plans = list(qs)
    if plans or (cliente_codigo or "").strip().lower() == "todos":
        return plans
    return list(
        PlanoPagamentoCliente.objects.filter(
            cliente_codigo="todos",
            loja_codigo=loja_codigo,
        ).order_by("plano_codigo")
    )


def _loja_to_dict(loja: Loja) -> dict:
    return {
        "LOJCOD": loja.codigo,
        "AGEDES": loja.razao_social or "",
        "AGEFAN": loja.nome_fantasia or "",
        "AGECGCCPF": loja.cnpj_cpf or "",
        "AGECGFRG": loja.ie_rg or "",
        "AGEPFPJ": loja.tipo_pf_pj or "",
        "AGETEL1": loja.telefone1 or "",
        "AGETEL2": loja.telefone2 or "",
        "AGEEND": loja.endereco or "",
        "AGEBAI": loja.bairro or "",
        "AGENUM": loja.numero or "",
        "AGECPL": loja.complemento or "",
        "AGECEP": loja.cep or "",
        "AGECORELE": loja.email or "",
        "AGECID": loja.cidade or "",
        "AGEEST": loja.estado or "",
    }


async def _ensure_auth_tables(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(150) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            vendor_code VARCHAR(50),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        ALTER TABLE api_users
        ADD COLUMN IF NOT EXISTS vendor_code VARCHAR(50);
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_trigger WHERE tgname = 'set_api_users_updated_at'
            ) THEN
                CREATE TRIGGER set_api_users_updated_at
                BEFORE UPDATE ON api_users
                FOR EACH ROW
                EXECUTE PROCEDURE update_updated_at_column();
            END IF;
        END$$;
        """
    )


async def _bootstrap_admin_user(conn: asyncpg.Connection) -> None:
    if not DEFAULT_ADMIN_USER or not DEFAULT_ADMIN_PASSWORD:
        return
    exists = await conn.fetchval("SELECT 1 FROM api_users WHERE username = $1;", DEFAULT_ADMIN_USER)
    if exists:
        return
    await conn.execute(
        """
        INSERT INTO api_users (username, password_hash, is_active)
        VALUES ($1, $2, TRUE);
        """,
        DEFAULT_ADMIN_USER,
        _hash_password(DEFAULT_ADMIN_PASSWORD),
    )


def _hash_password(password: str, iterations: int = 240000) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${base64.b64encode(dk).decode('ascii')}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iter_str, salt, b64_hash = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
    except Exception:
        return False
    new_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), iterations)
    return hmac.compare_digest(base64.b64encode(new_hash).decode("ascii"), b64_hash)


def _create_access_token(user_id: int, username: str, vendor_code: Optional[str] = None) -> str:
    now = datetime.now(dt_timezone.utc)
    exp = now + timedelta(minutes=JWT_EXPIRES_MINUTES)
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": exp,
        "iat": now,
    }
    if vendor_code:
        payload["vendor_code"] = vendor_code
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def _get_user_by_credentials(username: str, password: str) -> Optional[dict]:
    normalized_username = (username or "").strip()
    lowered = normalized_username.lower()
    pool = _get_auth_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, password_hash, vendor_code, is_active FROM api_users WHERE lower(username) = $1;",
            lowered,
        )
    if not row or not row["is_active"]:
        return None
    if not _verify_password(password, row["password_hash"]):
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "vendor_code": row.get("vendor_code"),
    }


async def _resolve_vendor_for_username(username: str, loja_codigo: str) -> Optional[dict]:
    raw_name = (username or "").strip().lower()
    if not raw_name:
        return None
    candidates = []
    if raw_name:
        candidates.append(raw_name)
    if "@" in raw_name:
        candidates.append(raw_name.split("@", 1)[0])
    simple = re.sub(r"[^a-z0-9]+", " ", raw_name).strip()
    if simple and simple not in candidates:
        candidates.append(simple)
    first_token = simple.split(" ", 1)[0] if simple else ""
    if first_token and first_token not in candidates:
        candidates.append(first_token)
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        for candidate in candidates:
            row = await conn.fetchrow(
                f"""
                SELECT vendedor_codigo, vendedor_nome
                FROM erp_clientes_vendedores
                WHERE lower(btrim(vendedor_nome)) = $1
                  AND {_sql_loja_equals_or_global("loja_codigo", 2)}
                ORDER BY vendedor_codigo
                LIMIT 1;
                """,
                candidate,
                loja_codigo,
            )
            if row:
                return {"vendor_code": row["vendedor_codigo"], "vendor_name": row["vendedor_nome"]}
        for candidate in candidates:
            row = await conn.fetchrow(
                f"""
                SELECT vendedor_codigo, vendedor_nome
                FROM erp_clientes_vendedores
                WHERE lower(btrim(vendedor_nome)) LIKE $1
                  AND {_sql_loja_equals_or_global("loja_codigo", 2)}
                ORDER BY vendedor_codigo
                LIMIT 1;
                """,
                f"{candidate}%",
                loja_codigo,
            )
            if row:
                return {"vendor_code": row["vendedor_codigo"], "vendor_name": row["vendedor_nome"]}
    return None


async def _resolve_vendor_by_code(vendor_code: Optional[str], loja_codigo: str) -> Optional[dict]:
    code = (vendor_code or "").strip()
    if not code:
        return None
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT vendedor_codigo, vendedor_nome
            FROM erp_clientes_vendedores
            WHERE ltrim(vendedor_codigo, '0') = ltrim($1, '0')
              AND {_sql_loja_equals_or_global("loja_codigo", 2)}
            ORDER BY vendedor_nome
            LIMIT 1;
            """,
            code,
            loja_codigo,
        )
    if row:
        return {"vendor_code": row["vendedor_codigo"], "vendor_name": row["vendedor_nome"]}
    return None

# -----------------------------------
# Modelo esperado pelo FastAPI
# -----------------------------------
class ProdutoSyncIn(BaseModel):
    codigo: str
    descricao_completa: str
    referencia: Optional[str] = None
    secao: Optional[str] = None
    grupo: Optional[str] = None
    subgrupo: Optional[str] = None
    unidade: Optional[str] = None
    ean: Optional[str] = None
    plu: str
    preco_normal: float = 0
    preco_promocao1: float = 0
    preco_promocao2: float = 0
    estoque_disponivel: float = 0
    custo: float = 0
    loja: str = "000001"
    row_hash: str = ""


class ClienteOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    cliente_codigo: Optional[str] = None
    cliente_status: Optional[int] = None
    cliente_razao_social: Optional[str] = None
    cliente_nome_fantasia: Optional[str] = None
    cliente_cnpj_cpf: Optional[str] = None
    cliente_tipo_pf_pj: Optional[str] = None
    cliente_endereco: Optional[str] = None
    cliente_numero: Optional[str] = None
    cliente_bairro: Optional[str] = None
    cliente_cidade: Optional[str] = None
    cliente_uf: Optional[str] = None
    cliente_cep: Optional[str] = None
    cliente_telefone1: Optional[str] = None
    cliente_telefone2: Optional[str] = None
    cliente_email: Optional[str] = None
    cliente_inscricao_municipal: Optional[str] = None
    limite_credito: Optional[float] = None
    row_hash: Optional[str] = None
    vendedor_codigo: Optional[str] = None
    vendedor_nome: Optional[str] = None
    ultima_venda_data: Optional[datetime] = None
    ultima_venda_valor: Optional[float] = None
    loja_codigo: Optional[str] = None
    updated_at: Optional[datetime] = None


class ClientesPageOut(BaseModel):
    total: int
    data: List[ClienteOut]
    page: Optional[int] = None
    page_size: Optional[int] = None


class UserOut(BaseModel):
    id: int
    username: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    vendor_code: Optional[str] = None
    vendor_name: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginResponse(BaseModel):
    token: TokenOut
    user: UserOut


class UserCreateRequest(BaseModel):
    username: str
    password: str
    vendor_code: Optional[str] = None
    is_active: bool = True


class PedidoItemIn(BaseModel):
    codigo_produto: str
    quantidade: Decimal
    valor_unitario: Decimal

    @field_validator("quantidade", "valor_unitario")
    def must_be_positive(cls, v, info):
        if v <= 0:
            raise ValueError("Valor deve ser maior que zero")
        return v


class PedidoIn(BaseModel):
    data_criacao: datetime
    total: Decimal
    cliente_id: str
    itens: List[PedidoItemIn]
    status: Optional[str] = None
    pagamento_status: Optional[str] = None
    forma_pagamento: Optional[str] = None
    frete_modalidade: Optional[str] = None
    vendedor_codigo: Optional[str] = None
    vendedor_nome: Optional[str] = None

    @field_validator("itens")
    def must_have_items(cls, v):
        if not v:
            raise ValueError("Lista de itens não pode ser vazia")
        return v

    @field_validator("status")
    def validate_status(cls, v):
        if v and v not in PEDIDO_STATUS_VALUES:
            raise ValueError(f"Status inválido. Opções: {sorted(PEDIDO_STATUS_VALUES)}")
        return v

    @field_validator("pagamento_status")
    def validate_pagamento_status(cls, v):
        if v and v not in PAGAMENTO_STATUS_VALUES:
            raise ValueError(f"Status de pagamento inválido. Opções: {sorted(PAGAMENTO_STATUS_VALUES)}")
        return v

    @field_validator("frete_modalidade")
    def validate_frete_modalidade(cls, v):
        if v and v not in FRETE_MODALIDADE_VALUES:
            raise ValueError(f"Modalidade de frete inválida. Opções: {sorted(FRETE_MODALIDADE_VALUES)}")
        return v


class PlanoPagamentoClienteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    CLICOD: str
    PLACOD: str
    PLADES: str
    PLAENT: Optional[Decimal] = Decimal("0")
    PLAINTPRI: Optional[int] = 0
    PLAINTPAR: Optional[int] = 0
    PLANUMPAR: Optional[int] = 1
    PLAVLRMIN: Optional[Decimal] = Decimal("0")
    PLAVLRACR: Optional[Decimal] = Decimal("0")

    @field_validator("CLICOD", "PLACOD", "PLADES")
    def require_non_empty(cls, v):
        if v is None or not str(v).strip():
            raise ValueError("Campo obrigatório.")
        return str(v).strip()


class PlanoPagamentoClienteOut(PlanoPagamentoClienteIn):
    pass


class SefazConfigIn(BaseModel):
    base_url: Optional[str] = None
    token: Optional[str] = None
    timeout: Optional[int] = None
    environment: Optional[str] = None
    certificate_file_b64: Optional[str] = None
    certificate_filename: Optional[str] = None
    certificate_password: Optional[str] = None
    clear_certificate: bool = False


class LojaIn(BaseModel):
    LOJCOD: str
    AGEDES: Optional[str] = None
    AGEFAN: Optional[str] = None
    AGECGCCPF: Optional[str] = None
    AGECGFRG: Optional[str] = None
    AGEPFPJ: Optional[str] = None
    AGETEL1: Optional[str] = None
    AGETEL2: Optional[str] = None
    AGEEND: Optional[str] = None
    AGEBAI: Optional[str] = None
    AGENUM: Optional[str] = None
    AGECPL: Optional[str] = None
    AGECEP: Optional[str] = None
    AGECORELE: Optional[str] = None
    AGECID: Optional[str] = None
    AGEEST: Optional[str] = None


PLANOS_PAGAMENTO_SCHEMA = {
    "type": "array",
    "items": PlanoPagamentoClienteIn.model_json_schema(),
    "examples": [
        [
            {
                "CLICOD": "000182",
                "PLACOD": "01",
                "PLADES": "A VISTA",
                "PLAENT": 1.0,
                "PLAINTPRI": 0,
                "PLAINTPAR": 0,
                "PLANUMPAR": 1,
                "PLAVLRMIN": 0.0,
                "PLAVLRACR": 0.0,
            }
        ]
    ],
}


async def require_jwt(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    if DISABLE_API_AUTH:
        return {"id": 0, "username": "auth_disabled"}
    app_token = (request.headers.get("X-App-Token") or "").strip()
    if APP_INTEGRATION_TOKEN and app_token == APP_INTEGRATION_TOKEN:
        return {"id": 0, "username": "app_token", "vendor_code": None, "is_app_token": True}
    auth_header = (request.headers.get("Authorization") or "").strip()
    if APP_INTEGRATION_TOKEN and auth_header:
        scheme, _, raw_value = auth_header.partition(" ")
        if scheme.lower() in ("bearer", "token", "app") and raw_value.strip() == APP_INTEGRATION_TOKEN:
            return {"id": 0, "username": "app_token", "vendor_code": None, "is_app_token": True}
    if not credentials or credentials.scheme.lower() != "bearer":
        logger.warning("Auth failed: missing/invalid bearer header")
        raise HTTPException(401, "Token ausente ou inválido", headers={"WWW-Authenticate": "Bearer"})
    raw_token = credentials.credentials
    try:
        payload = jwt.decode(raw_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.warning("Auth failed: expired token")
        raise HTTPException(401, "Token expirado", headers={"WWW-Authenticate": "Bearer"})
    except jwt.InvalidTokenError:
        logger.warning("Auth failed: invalid token")
        raise HTTPException(401, "Token inválido", headers={"WWW-Authenticate": "Bearer"})

    user_id = payload.get("sub")
    username = payload.get("username")
    if not user_id:
        raise HTTPException(403, "Token inválido")

    pool = _get_auth_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, is_active, vendor_code FROM api_users WHERE id = $1;",
            int(user_id),
        )
    if not row or not row["is_active"]:
        raise HTTPException(403, "Usuário inativo ou não encontrado")

    vendor_code = (payload.get("vendor_code") or "").strip() or None
    if not vendor_code:
        vendor_code = (row.get("vendor_code") or "").strip() or None
    if not vendor_code:
        admin_user = (DEFAULT_ADMIN_USER or "").strip()
        if not (admin_user and (username or "").lower() == admin_user.lower()):
            loja_codigo = getattr(request.state, "loja_codigo", None)
            if loja_codigo:
                resolved = await _resolve_vendor_for_username(username or "", loja_codigo)
                if resolved:
                    vendor_code = resolved.get("vendor_code")
                    logger.info(
                        "Auth vendor resolved by username=%s loja=%s vendor_code=%s",
                        username,
                        loja_codigo,
                        vendor_code,
                    )

    logger.info(
        "Auth ok path=%s user_id=%s username=%s vendor_code=%s",
        request.url.path,
        user_id,
        username,
        vendor_code or "",
    )
    return {
        "id": row["id"],
        "username": row["username"],
        "token_username": username,
        "vendor_code": vendor_code,
    }


async def optional_jwt(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    if DISABLE_API_AUTH:
        return {"id": 0, "username": "auth_disabled", "vendor_code": None, "is_app_token": True}
    app_token = (request.headers.get("X-App-Token") or "").strip()
    if APP_INTEGRATION_TOKEN and app_token == APP_INTEGRATION_TOKEN:
        return {"id": 0, "username": "app_token", "vendor_code": None, "is_app_token": True}
    auth_header = (request.headers.get("Authorization") or "").strip()
    if APP_INTEGRATION_TOKEN and auth_header:
        scheme, _, raw_value = auth_header.partition(" ")
        if scheme.lower() in ("bearer", "token", "app") and raw_value.strip() == APP_INTEGRATION_TOKEN:
            return {"id": 0, "username": "app_token", "vendor_code": None, "is_app_token": True}
    if not credentials or credentials.scheme.lower() != "bearer":
        return {"id": 0, "username": "app_token", "vendor_code": None, "is_app_token": True}
    raw_token = credentials.credentials
    try:
        payload = jwt.decode(raw_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.warning("Auth optional: expired token; fallback to anonymous")
        return {"id": 0, "username": "app_token", "vendor_code": None, "is_app_token": True}
    except jwt.InvalidTokenError:
        logger.warning("Auth optional: invalid token; fallback to anonymous")
        return {"id": 0, "username": "app_token", "vendor_code": None, "is_app_token": True}

    user_id = payload.get("sub")
    username = payload.get("username")
    if not user_id:
        raise HTTPException(403, "Token inválido")

    pool = _get_auth_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, is_active, vendor_code FROM api_users WHERE id = $1;",
            int(user_id),
        )
    if not row or not row["is_active"]:
        raise HTTPException(403, "Usuário inativo ou não encontrado")

    vendor_code = (payload.get("vendor_code") or "").strip() or None
    if not vendor_code:
        vendor_code = (row.get("vendor_code") or "").strip() or None
    if not vendor_code:
        admin_user = (DEFAULT_ADMIN_USER or "").strip()
        if not (admin_user and (username or "").lower() == admin_user.lower()):
            loja_codigo = getattr(request.state, "loja_codigo", None)
            if loja_codigo:
                resolved = await _resolve_vendor_for_username(username or "", loja_codigo)
                if resolved:
                    vendor_code = resolved.get("vendor_code")
                    logger.info(
                        "Auth vendor resolved by username=%s loja=%s vendor_code=%s",
                        username,
                        loja_codigo,
                        vendor_code,
                    )

    return {
        "id": row["id"],
        "username": row["username"],
        "token_username": username,
        "vendor_code": vendor_code,
    }


async def require_admin(token: dict = Depends(require_jwt)) -> dict:
    if DISABLE_API_AUTH:
        return token
    admin_user = (DEFAULT_ADMIN_USER or "").strip()
    if not admin_user:
        raise HTTPException(403, "Admin não configurado")
    if (token.get("username") or "").lower() != admin_user.lower():
        raise HTTPException(403, "Sem permissão")
    return token


def _is_admin_token(token: dict) -> bool:
    if DISABLE_API_AUTH:
        return True
    if token.get("is_app_token"):
        return True
    admin_user = (DEFAULT_ADMIN_USER or "").strip()
    if not admin_user:
        return False
    return (token.get("username") or "").lower() == admin_user.lower()


def _append_loja_scope(clauses: list[str], params: list, loja_codigo: str, column_name: str) -> None:
    if not loja_codigo:
        raise HTTPException(500, "Loja não resolvida")
    params.append(loja_codigo)
    clauses.append(_sql_loja_equals(column_name, len(params)))


def _append_loja_scope_with_global(clauses: list[str], params: list, loja_codigo: str, column_name: str) -> None:
    if not loja_codigo:
        raise HTTPException(500, "Loja não resolvida")
    params.append(loja_codigo)
    clauses.append(_sql_loja_equals_or_global(column_name, len(params)))


def _coalesce_vendor_code(token: dict, vendor_override: Optional[str]) -> Optional[str]:
    override = (vendor_override or "").strip()
    token_vendor = (token.get("vendor_code") or "").strip()
    if token.get("is_app_token"):
        return override or None
    if not _is_admin_token(token):
        if override and token_vendor:
            override_norm = _normalize_vendor_code(override)
            token_norm = _normalize_vendor_code(token_vendor)
            if override_norm and token_norm and override_norm != token_norm:
                raise HTTPException(403, "Vendedor não autorizado")
        vendor_code = token_vendor or override
        if not vendor_code:
            raise HTTPException(403, "Vendedor não identificado")
        return vendor_code
    return override or None


def _build_cliente_scope(
    token: dict,
    loja_codigo: str,
    vendor_override: Optional[str] = None,
) -> tuple[str, list[str], list]:
    vendor_code = _coalesce_vendor_code(token, vendor_override)
    if _is_admin_token(token) and not vendor_code:
        return "", [], []
    params: list = [loja_codigo]
    join_sql = (
        "JOIN erp_clientes_vendedores cv "
        "ON cv.cliente_codigo = c.cliente_codigo "
        f"AND {_sql_loja_equals_or_global('cv.loja_codigo', 1)}"
    )
    clauses: list[str] = []
    if vendor_code:
        params.append(vendor_code)
        clauses.append(_sql_vendor_equals("cv.vendedor_codigo", len(params)))
    return join_sql, clauses, params


def _build_cliente_vendedores_scope(
    token: dict,
    loja_codigo: str,
    vendor_override: Optional[str] = None,
) -> tuple[list[str], list]:
    clauses: list[str] = []
    params: list = []
    _append_loja_scope_with_global(clauses, params, loja_codigo, "cv.loja_codigo")
    vendor_code = _coalesce_vendor_code(token, vendor_override)
    if vendor_code:
        params.append(vendor_code)
        clauses.append(_sql_vendor_equals("cv.vendedor_codigo", len(params)))
    return clauses, params


def _build_cliente_fallback_scope(
    token: dict,
    loja_codigo: str,
    vendor_override: Optional[str] = None,
) -> tuple[list[str], list]:
    clauses: list[str] = []
    params: list = []
    _append_loja_scope_with_global(clauses, params, loja_codigo, "c.loja_codigo")
    vendor_code = _coalesce_vendor_code(token, vendor_override)
    if vendor_code:
        params.append(vendor_code)
        clauses.append(_sql_vendor_equals("c.vendedor_codigo", len(params)))
    return clauses, params


def _normalize_cliente_payload(data: dict) -> dict:
    if "rowhash" in data and not data.get("row_hash"):
        data["row_hash"] = data["rowhash"]
    data.pop("rowhash", None)
    return data
# -----------------------------------
# LISTAR PRODUTOS (tabela já existente)
# -----------------------------------
@app.get("/api/products", tags=["produtos"])
async def listar_produtos(
    token: dict = Depends(optional_jwt),
    loja_codigo: str = Depends(require_tenant),
    vendedor_id: Optional[str] = Query(None, alias="vendedor_id"),
    limit: Optional[int] = Query(None),
):
    pool = _get_data_pool()
    resolved_limit = limit if limit is not None and limit > 0 else None
    async with pool.acquire() as conn:
        try:
            base_sql = _produto_base_sql()
            sql = f"""
                WITH base AS (
                    {base_sql}
                    WHERE {_sql_loja_equals("pr.loja_codigo", 1)}
                )
                SELECT DISTINCT ON (codigo) *
                FROM base
                ORDER BY codigo, preco_updated_at DESC NULLS LAST
            """
            params: list = [loja_codigo]
            if resolved_limit:
                sql += f" LIMIT ${len(params) + 1}"
                params.append(resolved_limit)
            sql += ";"
            rows = await conn.fetch(sql, *params)
        except asyncpg.UndefinedTableError:
            base_sql = _produto_sync_base_sql()
            sql = f"""
                {base_sql}
                WHERE {_sql_loja_equals("p.loja", 1)}
                ORDER BY p.codigo
            """
            params = [loja_codigo]
            if resolved_limit:
                sql += f" LIMIT ${len(params) + 1}"
                params.append(resolved_limit)
            sql += ";"
            rows = await conn.fetch(sql, *params)
        output = []
        for row in rows:
            data = dict(row)
            data.pop("preco_updated_at", None)
            data.update(build_product_image_payload(data.get("codigo_imagem"), data.get("tipo_imagem")))
            output.append(_normalize_product_payload(data))
        return output


@app.get("/api/produtos-sync", tags=["produtos"])
async def listar_produtos_sync(
    q: Optional[str] = None,
    codigo: Optional[str] = None,
    plu: Optional[str] = None,
    ean: Optional[str] = None,
    loja: Optional[str] = None,
    token: dict = Depends(optional_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    clauses = []
    params = []

    if codigo:
        params.append(codigo)
        clauses.append(f"p.produto_codigo = ${len(params)}")
    if plu:
        params.append(plu)
        clauses.append(f"p.plu = ${len(params)}")
    if ean:
        params.append(ean)
        clauses.append(f"p.ean = ${len(params)}")
    if loja and not _loja_matches(loja, loja_codigo):
        raise HTTPException(403, "Loja não autorizada")
    _append_loja_scope(clauses, params, loja_codigo, "pr.loja_codigo")
    if q:
        params.append(f"%{q}%")
        clauses.append(
            f"(p.descricao_completa ILIKE ${len(params)} "
            f"OR p.referencia ILIKE ${len(params)} "
            f"OR p.produto_codigo ILIKE ${len(params)})"
        )

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        try:
            base_sql = _produto_base_sql()
            sql = f"""
                {base_sql}
                {where_sql}
                ORDER BY p.produto_codigo;
            """
            rows = await conn.fetch(sql, *params)
        except asyncpg.UndefinedTableError:
            sync_clauses = []
            sync_params = []
            if codigo:
                sync_params.append(codigo)
                sync_clauses.append(f"p.codigo = ${len(sync_params)}")
            if plu:
                sync_params.append(plu)
                sync_clauses.append(f"p.plu = ${len(sync_params)}")
            if ean:
                sync_params.append(ean)
                sync_clauses.append(f"p.ean = ${len(sync_params)}")
            if loja and not _loja_matches(loja, loja_codigo):
                raise HTTPException(403, "Loja não autorizada")
            _append_loja_scope(sync_clauses, sync_params, loja_codigo, "p.loja")
            if q:
                sync_params.append(f"%{q}%")
                sync_clauses.append(
                    f"(p.descricao_completa ILIKE ${len(sync_params)} "
                    f"OR p.referencia ILIKE ${len(sync_params)} "
                    f"OR p.codigo ILIKE ${len(sync_params)})"
                )
            sync_where_sql = f"WHERE {' AND '.join(sync_clauses)}" if sync_clauses else ""
            base_sql = _produto_sync_base_sql()
            sql = f"""
                {base_sql}
                {sync_where_sql}
                ORDER BY p.codigo;
            """
            rows = await conn.fetch(sql, *sync_params)
    output = []
    for row in rows:
        data = dict(row)
        data.update(build_product_image_payload(data.get("codigo_imagem"), data.get("tipo_imagem")))
        output.append(_normalize_product_payload(data))
    return output


@app.get("/api/produtos", tags=["produtos"])
async def listar_produtos_alias(
    q: Optional[str] = None,
    codigo: Optional[str] = None,
    plu: Optional[str] = None,
    ean: Optional[str] = None,
    loja: Optional[str] = None,
    token: dict = Depends(optional_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    return await listar_produtos_sync(
        q=q,
        codigo=codigo,
        plu=plu,
        ean=ean,
        loja=loja,
        token=token,
        loja_codigo=loja_codigo,
    )


@app.get("/api/produtos-sync/{codigo}", tags=["produtos"])
async def produto_por_codigo(
    codigo: str,
    token: dict = Depends(optional_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        try:
            base_sql = _produto_base_sql()
            row = await conn.fetchrow(
                f"""
                {base_sql}
                WHERE p.produto_codigo = $1
                  AND {_sql_loja_equals("pr.loja_codigo", 2)};
                """,
                codigo,
                loja_codigo,
            )
        except asyncpg.UndefinedTableError:
            base_sql = _produto_sync_base_sql()
            row = await conn.fetchrow(
                f"""
                {base_sql}
                WHERE p.codigo = $1
                  AND {_sql_loja_equals("p.loja", 2)};
                """,
                codigo,
                loja_codigo,
            )
    if not row:
        raise HTTPException(404, "Produto não encontrado")
    data = dict(row)
    data.update(build_product_image_payload(data.get("codigo_imagem"), data.get("tipo_imagem")))
    return data


@app.get("/api/produtos/search", tags=["produtos"])
async def buscar_produto_alias(
    q: str,
    token: dict = Depends(optional_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    return await buscar_produto(q=q, token=token, loja_codigo=loja_codigo)


@app.get("/api/produtos/{codigo}", tags=["produtos"])
async def produto_por_codigo_ou_plu(
    codigo: str,
    token: dict = Depends(optional_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        try:
            base_sql = _produto_base_sql()
            row = await conn.fetchrow(
                f"""
                {base_sql}
                WHERE p.produto_codigo = $1
                  AND {_sql_loja_equals("pr.loja_codigo", 2)};
                """,
                codigo,
                loja_codigo,
            )
            if not row:
                row = await conn.fetchrow(
                    f"""
                    {base_sql}
                    WHERE p.plu = $1
                      AND {_sql_loja_equals("pr.loja_codigo", 2)};
                    """,
                    codigo,
                    loja_codigo,
                )
        except asyncpg.UndefinedTableError:
            base_sql = _produto_sync_base_sql()
            row = await conn.fetchrow(
                f"""
                {base_sql}
                WHERE p.codigo = $1
                  AND {_sql_loja_equals("p.loja", 2)};
                """,
                codigo,
                loja_codigo,
            )
            if not row:
                row = await conn.fetchrow(
                    f"""
                    {base_sql}
                    WHERE p.plu = $1
                      AND {_sql_loja_equals("p.loja", 2)};
                    """,
                    codigo,
                    loja_codigo,
                )
    if not row:
        raise HTTPException(404, "Produto não encontrado")
    data = dict(row)
    data.update(build_product_image_payload(data.get("codigo_imagem"), data.get("tipo_imagem")))
    return data

# -----------------------------------
# BUSCAR POR PLU
# -----------------------------------
@app.get("/api/products/{plu}", tags=["produtos"])
async def produto_por_plu(
    plu: str,
    token: dict = Depends(optional_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        try:
            base_sql = _produto_base_sql()
            row = await conn.fetchrow(
                f"""
                {base_sql}
                WHERE p.plu = $1
                  AND {_sql_loja_equals("pr.loja_codigo", 2)};
                """,
                plu,
                loja_codigo,
            )
        except asyncpg.UndefinedTableError:
            base_sql = _produto_sync_base_sql()
            row = await conn.fetchrow(
                f"""
                {base_sql}
                WHERE p.plu = $1
                  AND {_sql_loja_equals("p.loja", 2)};
                """,
                plu,
                loja_codigo,
            )

    if not row:
        raise HTTPException(404, "Produto não encontrado")
    data = dict(row)
    data.update(build_product_image_payload(data.get("codigo_imagem"), data.get("tipo_imagem")))
    return data


# -----------------------------------
# BUSCA POR DESCRIÇÃO
# -----------------------------------
@app.get("/api/products/search", tags=["produtos"])
async def buscar_produto(
    q: str,
    token: dict = Depends(optional_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        try:
            base_sql = _produto_base_sql()
            rows = await conn.fetch(
                f"""
                    {base_sql}
                    WHERE p.descricao_completa ILIKE $1
                      AND {_sql_loja_equals("pr.loja_codigo", 2)}
                    LIMIT 50;
                """,
                f"%{q}%",
                loja_codigo,
            )
        except asyncpg.UndefinedTableError:
            base_sql = _produto_sync_base_sql()
            rows = await conn.fetch(
                f"""
                    {base_sql}
                    WHERE p.descricao_completa ILIKE $1
                      AND {_sql_loja_equals("p.loja", 2)}
                    LIMIT 50;
                """,
                f"%{q}%",
                loja_codigo,
            )
        output = []
        for row in rows:
            data = dict(row)
            data.update(build_product_image_payload(data.get("codigo_imagem"), data.get("tipo_imagem")))
            output.append(data)
        return output




# -----------------------------------
# SINCRONIZAÇÃO DE PRODUTOS
# -----------------------------------
@app.post("/api/products/sync", tags=["produtos"])
async def sync_products(
    produtos: List[ProdutoSyncIn],
    token: dict = Depends(require_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    pool = _get_data_pool()
    is_admin = _is_admin_token(token)

    insert_cadastro_sql = """
        INSERT INTO erp_produtos (
            produto_codigo,
            descricao_completa,
            referencia,
            secao,
            grupo,
            subgrupo,
            unidade,
            ean,
            plu,
            refplu,
            row_hash,
            updated_at
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW()
        )
        ON CONFLICT (produto_codigo) DO UPDATE SET
            descricao_completa = EXCLUDED.descricao_completa,
            referencia = EXCLUDED.referencia,
            secao = EXCLUDED.secao,
            grupo = EXCLUDED.grupo,
            subgrupo = EXCLUDED.subgrupo,
            unidade = EXCLUDED.unidade,
            ean = EXCLUDED.ean,
            plu = EXCLUDED.plu,
            refplu = EXCLUDED.refplu,
            row_hash = EXCLUDED.row_hash,
            updated_at = NOW();
    """

    insert_precos_sql = """
        INSERT INTO erp_produtos_precos (
            produto_codigo,
            loja_codigo,
            preco_normal,
            preco_promocao1,
            preco_promocao2,
            custo,
            updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, NOW())
        ON CONFLICT (produto_codigo, loja_codigo) DO UPDATE SET
            preco_normal = EXCLUDED.preco_normal,
            preco_promocao1 = EXCLUDED.preco_promocao1,
            preco_promocao2 = EXCLUDED.preco_promocao2,
            custo = EXCLUDED.custo,
            updated_at = NOW();
    """

    insert_estoque_sql = """
        INSERT INTO erp_produtos_estoque (
            produto_codigo,
            loja_codigo,
            estoque_disponivel,
            updated_at
        )
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (produto_codigo, loja_codigo) DO UPDATE SET
            estoque_disponivel = EXCLUDED.estoque_disponivel,
            updated_at = NOW();
    """

    insert_sync_sql = """
        INSERT INTO erp_produtos_sync (
            codigo,
            descricao_completa,
            referencia,
            secao,
            grupo,
            subgrupo,
            unidade,
            ean,
            plu,
            preco_normal,
            preco_promocao1,
            preco_promocao2,
            estoque_disponivel,
            loja,
            refplu,
            row_hash,
            custo,
            updated_at
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, NOW()
        )
        ON CONFLICT (codigo, loja) DO UPDATE SET
            descricao_completa = EXCLUDED.descricao_completa,
            referencia = EXCLUDED.referencia,
            secao = EXCLUDED.secao,
            grupo = EXCLUDED.grupo,
            subgrupo = EXCLUDED.subgrupo,
            unidade = EXCLUDED.unidade,
            ean = EXCLUDED.ean,
            plu = EXCLUDED.plu,
            preco_normal = EXCLUDED.preco_normal,
            preco_promocao1 = EXCLUDED.preco_promocao1,
            preco_promocao2 = EXCLUDED.preco_promocao2,
            estoque_disponivel = EXCLUDED.estoque_disponivel,
            refplu = EXCLUDED.refplu,
            row_hash = EXCLUDED.row_hash,
            custo = EXCLUDED.custo,
            updated_at = NOW();
    """
    def resolve_loja(payload_loja: Optional[str]) -> str:
        raw_loja = (payload_loja or "").strip()
        if raw_loja:
            if not is_admin and not _loja_matches(raw_loja, loja_codigo):
                raise HTTPException(403, "Loja não autorizada")
            return raw_loja
        return loja_codigo

    resolved_lojas = [resolve_loja(p.loja) for p in produtos]
    cadastro_payload = [
        (
            p.codigo,
            p.descricao_completa,
            p.referencia,
            p.secao,
            p.grupo,
            p.subgrupo,
            p.unidade,
            p.ean,
            p.plu,
            None,
            p.row_hash,
        )
        for p in produtos
    ]
    precos_payload = [
        (
            p.codigo,
            resolved_lojas[idx],
            p.preco_normal,
            p.preco_promocao1,
            p.preco_promocao2,
            p.custo,
        )
        for idx, p in enumerate(produtos)
    ]
    estoque_payload = [
        (
            p.codigo,
            resolved_lojas[idx],
            p.estoque_disponivel,
        )
        for idx, p in enumerate(produtos)
    ]
    sync_payload = [
        (
            p.codigo,
            p.descricao_completa,
            p.referencia,
            p.secao,
            p.grupo,
            p.subgrupo,
            p.unidade,
            p.ean,
            p.plu,
            p.preco_normal,
            p.preco_promocao1,
            p.preco_promocao2,
            p.estoque_disponivel,
            resolved_lojas[idx],
            None,
            p.row_hash,
            p.custo,
        )
        for idx, p in enumerate(produtos)
    ]

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(insert_cadastro_sql, cadastro_payload)
                await conn.executemany(insert_precos_sql, precos_payload)
                await conn.executemany(insert_estoque_sql, estoque_payload)
                await conn.executemany(insert_sync_sql, sync_payload)
        return {"status": "ok", "total": len(produtos)}

    except Exception as e:
        raise HTTPException(500, f"Erro ao sincronizar: {e}") from e


# -----------------------------------
# CLIENTES
# -----------------------------------
@app.get("/api/clientes", tags=["clientes"], response_model=ClientesPageOut)
async def listar_clientes(
    token: dict = Depends(optional_jwt),
    loja_codigo: str = Depends(require_tenant),
    vendedor_id: Optional[str] = Query(None, alias="vendedor_id"),
    cod_vendedor: Optional[str] = Query(None, alias="cod_vendedor"),
    limit: Optional[int] = Query(None, alias="limit"),
    page: int = Query(1, ge=1),
    page_size: Optional[int] = Query(None, ge=1),
):
    pool = _get_data_pool()
    vendor_override = (vendedor_id or cod_vendedor or "").strip() or None
    if limit is not None and limit > 0 and not page_size:
        page_size = limit
    join_sql, clauses, params = _build_cliente_scope(token, loja_codigo, vendor_override)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with pool.acquire() as conn:
        try:
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM erp_clientes c {join_sql} {where_sql};",
                *params,
            )
            if page_size:
                offset = (page - 1) * page_size
                params_with_page = [*params, offset, page_size]
                rows = await conn.fetch(
                    f"""
                    SELECT c.*
                    FROM erp_clientes c
                    {join_sql}
                    {where_sql}
                    ORDER BY c.cliente_codigo
                    OFFSET ${len(params) + 1} LIMIT ${len(params) + 2};
                    """,
                    *params_with_page,
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT c.*
                    FROM erp_clientes c
                    {join_sql}
                    {where_sql}
                    ORDER BY c.cliente_codigo;
                    """,
                    *params,
                )
        except asyncpg.UndefinedTableError:
            fallback_clauses, fallback_params = _build_cliente_fallback_scope(
                token,
                loja_codigo,
                vendor_override,
            )
            fallback_where_sql = f"WHERE {' AND '.join(fallback_clauses)}" if fallback_clauses else ""
            total = await conn.fetchval(
                f"SELECT COUNT(DISTINCT c.cliente_codigo) FROM erp_clientes_vendedores c {fallback_where_sql};",
                *fallback_params,
            )
            if page_size:
                offset = (page - 1) * page_size
                params_with_page = [*fallback_params, offset, page_size]
                rows = await conn.fetch(
                    f"""
                    SELECT DISTINCT ON (c.cliente_codigo) c.*
                    FROM erp_clientes_vendedores c
                    {fallback_where_sql}
                    ORDER BY c.cliente_codigo, c.updated_at DESC
                    OFFSET ${len(fallback_params) + 1} LIMIT ${len(fallback_params) + 2};
                    """,
                    *params_with_page,
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT DISTINCT ON (c.cliente_codigo) c.*
                    FROM erp_clientes_vendedores c
                    {fallback_where_sql}
                    ORDER BY c.cliente_codigo, c.updated_at DESC;
                    """,
                    *fallback_params,
                )

    data = [_normalize_cliente_payload(dict(r)) for r in rows]
    response = {
        "total": total,
        "data": data,
    }
    if page_size:
        response["page"] = page
        response["page_size"] = page_size
    return response


@app.get("/api/inadimplencia", tags=["inadimplencia"])
async def listar_inadimplencia(
    token: dict = Depends(optional_jwt),
    loja_codigo: str = Depends(require_tenant),
    cod_loja: Optional[str] = Query(None),
    cod_cliente: Optional[str] = Query(None),
    cod_vendedor: Optional[str] = Query(None),
    vencido: Optional[bool] = Query(None),
    limit: Optional[int] = Query(None),
):
    pool = _get_data_pool()
    clauses: list[str] = []
    params: list = []

    loja_param = (cod_loja or "").strip()
    if loja_param and not _loja_matches(loja_param, loja_codigo):
        raise HTTPException(403, "Loja não autorizada")
    _append_loja_scope(clauses, params, loja_param or loja_codigo, "cod_loja")

    if cod_cliente:
        params.append(cod_cliente.strip())
        clauses.append(f"cod_cliente = ${len(params)}")
    if cod_vendedor:
        params.append(cod_vendedor.strip())
        clauses.append(_sql_vendor_equals("cod_vendedor", len(params)))
    if vencido is True:
        clauses.append("COALESCE(vencimento_real, vencimento) IS NOT NULL")
        clauses.append("COALESCE(vencimento_real, vencimento) <= CURRENT_DATE")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT *
        FROM erp_inadimplencia
        {where_sql}
        ORDER BY vencimento NULLS LAST, num_titulo
    """
    if limit is not None and limit > 0:
        sql += f" LIMIT ${len(params) + 1}"
        params.append(limit)
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [_normalize_cliente_payload(dict(r)) for r in rows]


@app.get("/api/clientes/lista", tags=["clientes"], response_model=List[ClienteOut])
async def listar_clientes_lista(
    token: dict = Depends(optional_jwt),
    loja_codigo: str = Depends(require_tenant),
    vendedor_id: Optional[str] = Query(None, alias="vendedor_id"),
    cod_vendedor: Optional[str] = Query(None, alias="cod_vendedor"),
):
    pool = _get_data_pool()
    vendor_override = (vendedor_id or cod_vendedor or "").strip() or None
    join_sql, clauses, params = _build_cliente_scope(token, loja_codigo, vendor_override)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                f"""
                SELECT c.*
                FROM erp_clientes c
                {join_sql}
                {where_sql}
                ORDER BY c.cliente_codigo;
                """,
                *params,
            )
        except asyncpg.UndefinedTableError:
            fallback_clauses, fallback_params = _build_cliente_fallback_scope(
                token,
                loja_codigo,
                vendor_override,
            )
            fallback_where_sql = f"WHERE {' AND '.join(fallback_clauses)}" if fallback_clauses else ""
            rows = await conn.fetch(
                f"""
                SELECT DISTINCT ON (c.cliente_codigo) c.*
                FROM erp_clientes_vendedores c
                {fallback_where_sql}
                ORDER BY c.cliente_codigo, c.updated_at DESC;
                """,
                *fallback_params,
            )
    return [_normalize_cliente_payload(dict(r)) for r in rows]


@app.get("/api/clientes/lista", tags=["clientes"], response_model=List[ClienteOut])
async def listar_clientes_lista(
    token: dict = Depends(optional_jwt),
    loja_codigo: str = Depends(require_tenant),
    vendedor_id: Optional[str] = Query(None, alias="vendedor_id"),
    cod_vendedor: Optional[str] = Query(None, alias="cod_vendedor"),
):
    pool = _get_data_pool()
    vendor_override = (vendedor_id or cod_vendedor or "").strip() or None
    join_sql, clauses, params = _build_cliente_scope(token, loja_codigo, vendor_override)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                f"""
                SELECT c.*
                FROM erp_clientes c
                {join_sql}
                {where_sql}
                ORDER BY c.cliente_codigo;
                """,
                *params,
            )
        except asyncpg.UndefinedTableError:
            fallback_clauses, fallback_params = _build_cliente_fallback_scope(
                token,
                loja_codigo,
                vendor_override,
            )
            fallback_where_sql = f"WHERE {' AND '.join(fallback_clauses)}" if fallback_clauses else ""
            rows = await conn.fetch(
                f"""
                SELECT DISTINCT ON (c.cliente_codigo) c.*
                FROM erp_clientes_vendedores c
                {fallback_where_sql}
                ORDER BY c.cliente_codigo, c.updated_at DESC;
                """,
                *fallback_params,
            )
    return [dict(r) for r in rows]


@app.get("/api/clientes/{cliente_codigo}", tags=["clientes"], response_model=ClienteOut)
async def cliente_por_codigo(
    cliente_codigo: str,
    token: dict = Depends(optional_jwt),
    loja_codigo: str = Depends(require_tenant),
    vendedor_id: Optional[str] = Query(None, alias="vendedor_id"),
):
    pool = _get_data_pool()
    vendor_override = (vendedor_id or "").strip() or None
    join_sql, clauses, params = _build_cliente_scope(token, loja_codigo, vendor_override)
    params.append(cliente_codigo)
    clauses.append(f"c.cliente_codigo = ${len(params)}")
    where_sql = " AND ".join(clauses)
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                f"""
                SELECT c.*
                FROM erp_clientes c
                {join_sql}
                WHERE {where_sql};
                """,
                *params,
            )
        except asyncpg.UndefinedTableError:
            fallback_clauses, fallback_params = _build_cliente_fallback_scope(
                token,
                loja_codigo,
                vendor_override,
            )
            fallback_params.append(cliente_codigo)
            fallback_clauses.append(f"c.cliente_codigo = ${len(fallback_params)}")
            fallback_where_sql = " AND ".join(fallback_clauses)
            row = await conn.fetchrow(
                f"""
                SELECT c.*
                FROM erp_clientes_vendedores c
                WHERE {fallback_where_sql}
                ORDER BY c.updated_at DESC
                LIMIT 1;
                """,
                *fallback_params,
            )
    if not row:
        raise HTTPException(404, "Cliente não encontrado")
    return _normalize_cliente_payload(dict(row))


@app.get("/api/clientes/search", tags=["clientes"], response_model=List[ClienteOut])
async def buscar_cliente(
    q: str,
    token: dict = Depends(optional_jwt),
    loja_codigo: str = Depends(require_tenant),
    vendedor_id: Optional[str] = Query(None, alias="vendedor_id"),
):
    pool = _get_data_pool()
    like = f"%{q}%"
    vendor_override = (vendedor_id or "").strip() or None
    join_sql, clauses, params = _build_cliente_scope(token, loja_codigo, vendor_override)
    params.append(like)
    clauses.append(
        f"(c.cliente_razao_social ILIKE ${len(params)} "
        f"OR c.cliente_nome_fantasia ILIKE ${len(params)} "
        f"OR c.cliente_cnpj_cpf ILIKE ${len(params)})"
    )
    where_sql = " AND ".join(clauses)
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                f"""
                SELECT c.*
                FROM erp_clientes c
                {join_sql}
                WHERE {where_sql}
                """,
                *params,
            )
        except asyncpg.UndefinedTableError:
            fallback_clauses, fallback_params = _build_cliente_fallback_scope(
                token,
                loja_codigo,
                vendor_override,
            )
            fallback_params.append(like)
            fallback_clauses.append(
                f"(c.cliente_razao_social ILIKE ${len(fallback_params)} "
                f"OR c.cliente_nome_fantasia ILIKE ${len(fallback_params)} "
                f"OR c.cliente_cnpj_cpf ILIKE ${len(fallback_params)})"
            )
            fallback_where_sql = " AND ".join(fallback_clauses)
            rows = await conn.fetch(
                f"""
                SELECT DISTINCT ON (c.cliente_codigo) c.*
                FROM erp_clientes_vendedores c
                WHERE {fallback_where_sql}
                ORDER BY c.cliente_codigo, c.updated_at DESC
                """,
                *fallback_params,
            )
    return [_normalize_cliente_payload(dict(r)) for r in rows]


# -----------------------------------
# PLANOS DE PAGAMENTO (Postgres)
# -----------------------------------
def _ensure_plano_pagamentos_schema() -> None:
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('public.plano_pagamento_cliente');")
        if cur.fetchone()[0] is None:
            return
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'plano_pagamento_cliente';
            """
        )
        cols = {row[0] for row in cur.fetchall()}
        if "loja_codigo" not in cols:
            cur.execute(
                """
                ALTER TABLE plano_pagamento_cliente
                ADD COLUMN loja_codigo VARCHAR(10) NOT NULL DEFAULT '00001';
                """
            )
        if "dias_primeira_parcela" not in cols:
            cur.execute(
                """
                ALTER TABLE plano_pagamento_cliente
                ADD COLUMN dias_primeira_parcela INTEGER;
                """
            )
        cur.execute(
            """
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND indexname = 'idx_plano_pag_cli_loja'
            LIMIT 1;
            """
        )
        if cur.fetchone() is None:
            cur.execute(
                """
                CREATE INDEX idx_plano_pag_cli_loja
                ON plano_pagamento_cliente (loja_codigo);
                """
            )
        cur.execute(
            """
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'uniq_plano_pagamentos_clientes'
            LIMIT 1;
            """
        )
        if cur.fetchone() is None:
            cur.execute(
                """
                ALTER TABLE plano_pagamento_cliente
                ADD CONSTRAINT uniq_plano_pagamentos_clientes
                UNIQUE (cliente_codigo, loja_codigo, plano_codigo);
                """
            )

def _normalize_plano(item: PlanoPagamentoClienteIn) -> PlanoPagamentoClienteIn:
    if item.PLANUMPAR is None:
        item.PLANUMPAR = 1
    if item.PLAENT is None:
        item.PLAENT = Decimal("0")
    if item.PLAVLRMIN is None:
        item.PLAVLRMIN = Decimal("0")
    if item.PLAVLRACR is None:
        item.PLAVLRACR = Decimal("0")
    if item.PLAINTPRI is None:
        item.PLAINTPRI = 0
    if item.PLAINTPAR is None:
        item.PLAINTPAR = 0
    return item


def _sync_planos_pagamento_clientes(payload: List[dict], loja_codigo: str) -> dict:
    _ensure_plano_pagamentos_schema()
    now = dj_timezone.now()
    valid_items: List[PlanoPagamentoClienteIn] = []
    erros = 0
    for idx, raw in enumerate(payload, start=1):
        try:
            item = PlanoPagamentoClienteIn.model_validate(raw)
            valid_items.append(_normalize_plano(item))
        except ValidationError as exc:
            erros += 1
            logger.warning("Plano inválido linha %s: %s", idx, exc)

    keys = {(item.CLICOD, item.PLACOD, loja_codigo) for item in valid_items}
    existentes = set(
        PlanoPagamentoCliente.objects.filter(
            models.Q(*[models.Q(cliente_codigo=c, plano_codigo=p, loja_codigo=l) for c, p, l in keys])
        ).values_list("cliente_codigo", "plano_codigo", "loja_codigo")
    ) if keys else set()

    inseridos = len(keys - existentes)
    atualizados = len(keys & existentes)

    plans = [
        PlanoPagamentoCliente(
            cliente_codigo=item.CLICOD,
            loja_codigo=loja_codigo,
            plano_codigo=item.PLACOD,
            plano_descricao=item.PLADES,
            parcelas=item.PLANUMPAR,
            dias_primeira_parcela=item.PLAINTPRI,
            dias_entre_parcelas=item.PLAINTPAR,
            valor_minimo=item.PLAVLRMIN,
            valor_acrescimo=item.PLAVLRACR,
            updated_at=now,
        )
        for item in valid_items
    ]
    if plans:
        PlanoPagamentoCliente.objects.bulk_create(
            plans,
            update_conflicts=True,
            unique_fields=["cliente_codigo", "loja_codigo", "plano_codigo"],
            update_fields=[
                "plano_descricao",
                "parcelas",
                "dias_primeira_parcela",
                "dias_entre_parcelas",
                "valor_minimo",
                "valor_acrescimo",
                "updated_at",
            ],
        )

    return {
        "total_recebidos": len(payload),
        "inseridos": inseridos,
        "atualizados": atualizados,
        "erros": erros,
    }


@app.get("/api/planos-pagamento-cliente", tags=["planos_pagamento"])
async def listar_planos_pagamento_cliente(
    cliente_codigo: str = Query(...),
    token: dict = Depends(require_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    await run_in_threadpool(_ensure_plano_pagamentos_schema)
    plans = await run_in_threadpool(_fetch_planos_pagamento, cliente_codigo, loja_codigo)
    data = [_plan_to_dict(plan) for plan in plans]
    return {"cliente_codigo": cliente_codigo, "total": len(data), "data": data}


@app.get("/api/planos-pagamento-cliente/{cliente_codigo}", tags=["planos_pagamento"])
async def listar_planos_pagamento_cliente_path(
    cliente_codigo: str,
    token: dict = Depends(require_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    await run_in_threadpool(_ensure_plano_pagamentos_schema)
    plans = await run_in_threadpool(_fetch_planos_pagamento, cliente_codigo, loja_codigo)
    data = [_plan_to_dict(plan) for plan in plans]
    return {"cliente_codigo": cliente_codigo, "total": len(data), "data": data}


@app.post("/api/planos-pagamento-clientes/sync", tags=["planos_pagamento"])
async def sync_planos_pagamento_clientes(
    payload: list = Body(..., openapi_extra=PLANOS_PAGAMENTO_SCHEMA),
    token: dict = Depends(require_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    raise HTTPException(410, "Sincronizacao de planos desativada. Use o admin.")


# -----------------------------------
# LOJAS (Postgres)
# -----------------------------------
def _sync_lojas(payload: List[LojaIn]) -> int:
    now = dj_timezone.now()
    lojas = [
        Loja(
            codigo=item.LOJCOD,
            razao_social=item.AGEDES or "",
            nome_fantasia=item.AGEFAN or "",
            cnpj_cpf=item.AGECGCCPF or "",
            ie_rg=item.AGECGFRG or "",
            tipo_pf_pj=item.AGEPFPJ or "",
            telefone1=item.AGETEL1 or "",
            telefone2=item.AGETEL2 or "",
            endereco=item.AGEEND or "",
            bairro=item.AGEBAI or "",
            numero=item.AGENUM or "",
            complemento=item.AGECPL or "",
            cep=item.AGECEP or "",
            email=item.AGECORELE or "",
            cidade=item.AGECID or "",
            estado=item.AGEEST or "",
            updated_at=now,
        )
        for item in payload
    ]
    if not lojas:
        return 0
    Loja.objects.bulk_create(
        lojas,
        update_conflicts=True,
        unique_fields=["codigo"],
        update_fields=[
            "razao_social",
            "nome_fantasia",
            "cnpj_cpf",
            "ie_rg",
            "tipo_pf_pj",
            "telefone1",
            "telefone2",
            "endereco",
            "bairro",
            "numero",
            "complemento",
            "cep",
            "email",
            "cidade",
            "estado",
            "updated_at",
        ],
    )
    return len(lojas)


@app.get("/api/lojas", tags=["lojas"])
async def listar_lojas(
    q: Optional[str] = None,
    token: dict = Depends(require_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    def _fetch():
        codigo_regex = _loja_regex(loja_codigo)
        qs = Loja.objects.filter(codigo__regex=codigo_regex).order_by("codigo")
        if q:
            return list(
                qs.filter(
                    models.Q(codigo__icontains=q)
                    | models.Q(razao_social__icontains=q)
                    | models.Q(nome_fantasia__icontains=q)
                    | models.Q(cidade__icontains=q)
                    | models.Q(estado__icontains=q)
                )
            )
        return list(qs)

    lojas = await run_in_threadpool(_fetch)
    return [_loja_to_dict(loja) for loja in lojas]


@app.get("/api/lojas/{loja_codigo}", tags=["lojas"])
async def detalhar_loja(
    loja_codigo: str,
    token: dict = Depends(require_jwt),
    loja_tenant: str = Depends(require_tenant),
):
    if not _loja_matches(loja_codigo, loja_tenant):
        raise HTTPException(403, "Loja não autorizada")
    codigo_regex = _loja_regex(loja_codigo)
    loja = await run_in_threadpool(lambda: Loja.objects.filter(codigo__regex=codigo_regex).first())
    if not loja:
        raise HTTPException(404, "Loja não encontrada")
    return _loja_to_dict(loja)


@app.post("/api/lojas/sync", tags=["lojas"])
async def sync_lojas(
    payload: List[LojaIn],
    token: dict = Depends(require_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    if not _is_admin_token(token):
        for item in payload:
            if item.LOJCOD and not _loja_matches(item.LOJCOD, loja_codigo):
                raise HTTPException(403, "Loja não autorizada")
    total = await run_in_threadpool(_sync_lojas, payload)
    return {"status": "ok", "total": total}


# -----------------------------------
# ROTA RAIZ
# -----------------------------------
@app.get("/")
async def root(token: dict = Depends(require_jwt)):
    return {"status": "API funcionando", "user_id": token.get("id")}


@app.get("/api/me", tags=["auth"])
async def api_me(
    token: dict = Depends(require_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    return {
        "id": token.get("id"),
        "username": token.get("username"),
        "vendor_code": token.get("vendor_code"),
        "loja_codigo": loja_codigo,
    }


# -----------------------------------
# SEFAZ CONFIG (Postgres)
# -----------------------------------
def _handle_sefaz_submit(data: dict, files: dict) -> dict:
    config = SefazConfiguration.load()
    form = SefazConfigurationForm(data, files, instance=config)
    if form.is_valid():
        cfg = form.save(commit=False)
        cfg.updated_by = None
        cfg.save()
        return {"data": _serialize_sefaz_config(cfg)}
    return {"errors": form.errors}


@app.get("/api/sefaz/config", tags=["sefaz"])
async def get_sefaz_config(token: dict = Depends(require_jwt)):
    cfg = await run_in_threadpool(SefazConfiguration.load)
    return _serialize_sefaz_config(cfg)


@app.put("/api/sefaz/config", tags=["sefaz"])
@app.patch("/api/sefaz/config", tags=["sefaz"])
async def update_sefaz_config(
    payload: SefazConfigIn,
    token: dict = Depends(require_jwt),
):
    data = {
        "base_url": (payload.base_url or "").strip(),
        "token": (payload.token or "").strip(),
        "timeout": payload.timeout,
        "environment": payload.environment,
        "certificate_password": (payload.certificate_password or "").strip(),
        "clear_certificate": bool(payload.clear_certificate),
    }
    files = {}
    if payload.certificate_file_b64:
        filename = payload.certificate_filename or "certificate.pfx"
        try:
            content = base64.b64decode(payload.certificate_file_b64)
        except Exception:
            return JSONResponse({"certificate_file_b64": ["Arquivo inválido (base64)."]}, status_code=400)
        files["certificate_file"] = SimpleUploadedFile(filename, content)

    result = await run_in_threadpool(_handle_sefaz_submit, data, files)
    if "errors" in result:
        return JSONResponse(result["errors"], status_code=400)
    return result["data"]


@app.get("/api/companies/{pk}/nfe", tags=["sefaz"])
async def company_nfe(
    pk: int,
    last_nsu: Optional[str] = None,
    nsu: Optional[str] = None,
    access_key: Optional[str] = None,
    issued_from: Optional[str] = None,
    issued_until: Optional[str] = None,
    authorized_from: Optional[str] = None,
    authorized_until: Optional[str] = None,
    token: dict = Depends(require_jwt),
):
    def _run_query():
        company = Company.objects.get(pk=pk)
        params = {
            "last_nsu": last_nsu,
            "nsu": nsu,
            "access_key": access_key,
            "issued_from": issued_from,
            "issued_until": issued_until,
            "authorized_from": authorized_from,
            "authorized_until": authorized_until,
        }
        params, result, error, sefaz_ready = prepare_company_nfe_query(company, params)
        if not sefaz_ready:
            return {"status": 503, "payload": {"error": error, "params": params}}
        if error:
            return {"status": 400, "payload": {"error": error, "params": params}}
        if not result:
            return {"status": 200, "payload": {"message": "Nenhuma resposta foi retornada pela SEFAZ.", "params": params}}
        documents = [serialize_nfe_document(doc) for doc in result.documents]
        return {
            "status": 200,
            "payload": {
                "company": {"id": company.pk, "name": company.name, "tax_id": company.tax_id},
                "params": params,
                "status_code": result.status_code,
                "status_message": result.status_message,
                "last_nsu": result.last_nsu,
                "max_nsu": result.max_nsu,
                "count": len(documents),
                "documents": documents,
            },
        }

    result = await run_in_threadpool(_run_query)
    return JSONResponse(result["payload"], status_code=result["status"])


async def _login(payload: LoginRequest, loja_codigo: str) -> dict:
    user = await _get_user_by_credentials(payload.username.strip(), payload.password)
    if not user:
        raise HTTPException(401, "Usuário ou senha inválidos", headers={"WWW-Authenticate": "Bearer"})
    vendor = await _resolve_vendor_by_code(user.get("vendor_code"), loja_codigo)
    # Fallback por nome apenas se não houver vendor_code cadastrado
    if not vendor:
        vendor = await _resolve_vendor_for_username(payload.username, loja_codigo)
    vendor_code = vendor.get("vendor_code") if vendor else None
    token = _create_access_token(user["id"], user["username"], vendor_code)
    user_data = {
        "id": user["id"],
        "username": user["username"],
        "is_active": True,
        "created_at": dj_timezone.now(),
        "updated_at": dj_timezone.now(),
        "vendor_code": vendor.get("vendor_code") if vendor else None,
        "vendor_name": vendor.get("vendor_name") if vendor else None,
    }
    token_out = TokenOut(
        access_token=token,
        token_type="bearer",
        expires_in=JWT_EXPIRES_MINUTES * 60,
    )
    return {"token": token_out, "user": user_data}


@auth_router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    loja_codigo: str = Depends(require_tenant),
):
    return await _login(payload, loja_codigo)


@app.post("/api/login", tags=["auth"])
async def login_alias(
    payload: LoginRequest,
    request: Request,
    loja_codigo: str = Depends(require_tenant),
):
    return await _login(payload, loja_codigo)


@auth_router.post("/users", response_model=UserOut, dependencies=[Depends(require_admin)])
async def create_user(
    payload: UserCreateRequest,
    request: Request,
    loja_codigo: str = Depends(require_tenant),
):
    username = (payload.username or "").strip()
    if not username:
        raise HTTPException(400, "Usuário inválido")
    if not payload.password:
        raise HTTPException(400, "Senha inválida")

    password_hash = _hash_password(payload.password)
    pool = _get_auth_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO api_users (username, password_hash, vendor_code, is_active)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (username) DO UPDATE SET
                password_hash = EXCLUDED.password_hash,
                vendor_code = EXCLUDED.vendor_code,
                is_active = EXCLUDED.is_active
            RETURNING id, username, is_active, created_at, updated_at, vendor_code;
            """,
            username,
            password_hash,
            payload.vendor_code,
            payload.is_active,
        )

    vendor = await _resolve_vendor_by_code(row.get("vendor_code"), loja_codigo)
    return {
        "id": row["id"],
        "username": row["username"],
        "is_active": row["is_active"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "vendor_code": row.get("vendor_code"),
        "vendor_name": vendor.get("vendor_name") if vendor else None,
    }


# -----------------------------------
# IMAGENS (MinIO)
# -----------------------------------
@images_router.post("/upload", tags=["imagens"])
async def upload_imagem(token: dict = Depends(require_jwt)):
    detail = "Upload de imagens é feito exclusivamente via MinIO Client (mc). A API não realiza upload."
    if not DISABLE_IMAGE_UPLOAD:
        detail = f"{detail} (DISABLE_IMAGE_UPLOAD=false)"
    raise HTTPException(503, detail)


@images_router.get("/{tipo}/{codigo}", tags=["imagens"])
async def resolver_imagem(tipo: str, codigo: str):
    key = _build_image_key(tipo, (codigo or "").strip())
    return {"url": _public_image_url(key)}


# -----------------------------------
# PEDIDOS
# -----------------------------------
def _resolve_cliente(cliente_id: str, loja_codigo: Optional[str] = None) -> Client:
    client_code = (cliente_id or "").strip()
    if client_code == "0":
        return Client.get_default_consumer()

    def find_client(code: str) -> Optional[Client]:
        if not code:
            return None
        candidate = None
        if code.isdigit():
            try:
                candidate = Client.objects.filter(pk=int(code)).first()
            except Exception:
                candidate = None
        if not candidate:
            candidate = Client.objects.filter(code=code).first()
        return candidate

    # 1) Busca direta por PK ou código interno informado
    cliente = find_client(client_code)
    if cliente:
        return cliente

    # 2) Fallback: tentar resolver pelo staging de clientes sincronizados (ERP)
    sync_qs = ClienteSync.objects.filter(cliente_codigo=client_code)
    if loja_codigo:
        sync_qs = sync_qs.filter(loja_codigo=loja_codigo)
    sync_entry = sync_qs.first()
    if not sync_entry and client_code.isdigit():
        stripped = client_code.lstrip("0")
        if stripped:
            sync_qs = ClienteSync.objects.filter(cliente_codigo=stripped)
            if loja_codigo:
                sync_qs = sync_qs.filter(loja_codigo=loja_codigo)
            sync_entry = sync_qs.first()

    if sync_entry:
        doc_digits = "".join(ch for ch in (sync_entry.cliente_cnpj_cpf or "") if ch.isdigit())
        code_candidates = [
            doc_digits,
            sync_entry.cliente_codigo,
            sync_entry.cliente_codigo.lstrip("0") if sync_entry.cliente_codigo else None,
        ]

        # 2a) Tenta encontrar por código/documento
        for candidate_code in code_candidates:
            cliente = find_client(candidate_code or "")
            if cliente:
                return cliente

        # 2b) Se não existe em Client, cria um registro básico a partir do staging
        new_code = next((c for c in code_candidates if c), client_code)
        email = (sync_entry.cliente_email or "").strip() or f"{new_code}@placeholder.local"
        nome = (sync_entry.cliente_razao_social or sync_entry.cliente_nome_fantasia or "Cliente ERP").strip()
        nome_fantasia = (sync_entry.cliente_nome_fantasia or sync_entry.vendedor_nome or "").strip()
        person_type = "J" if len(doc_digits) > 11 else "F"

        cliente = Client.objects.create(
            person_type=person_type,
            code=new_code,
            document=doc_digits or (new_code or "").ljust(11, "0")[:14],
            first_name=nome[:150] or "Cliente ERP",
            last_name=nome_fantasia[:150],
            email=email,
            phone=(sync_entry.cliente_telefone1 or sync_entry.cliente_telefone2 or ""),
            state_registration=sync_entry.cliente_inscricao_municipal or "",
            address=sync_entry.cliente_endereco or "",
            number=sync_entry.cliente_numero or "",
            district=sync_entry.cliente_bairro or "",
            city=sync_entry.cliente_cidade or "",
            state=(sync_entry.cliente_uf or "")[:2],
            zip_code=sync_entry.cliente_cep or "",
        )
        return cliente

    raise HTTPException(400, f"Cliente não encontrado: {cliente_id}")


def _resolve_produto(codigo_produto: str) -> Product:
    raw = (codigo_produto or "").strip()
    normalized = Product.normalize_code(raw)
    produto = None

    # ProdutoSync nao expõe timestamp em algumas bases; escolhemos um fallback seguro.
    produto_sync_ordering = "-updated_at"
    if not any(field.name == "updated_at" for field in ProdutoSync._meta.fields):
        produto_sync_ordering = "-codigo"

    # 1) PLU (ERP Studio envia índice PLU). Tentamos:
    #    a) match direto em Product.plu_code (raw, só dígitos, sem zeros à esquerda)
    #    b) fallback via tabela erp_produtos_sync para descobrir o código e então localizar Product
    if raw:
        digits = "".join(ch for ch in raw if ch.isdigit())
        stripped = digits.lstrip("0") or ("0" if digits else None)
        plu_candidates = [raw]
        if digits and digits not in plu_candidates:
            plu_candidates.append(digits)
        if stripped and stripped not in plu_candidates:
            plu_candidates.append(stripped)

        produto = Product.objects.filter(plu_code__in=plu_candidates).first()
        if not produto:
            psync = ProdutoSync.objects.filter(plu__in=plu_candidates).order_by(produto_sync_ordering).first()
            if psync and psync.codigo:
                code_from_sync = str(psync.codigo).strip()
                norm_code = Product.normalize_code(code_from_sync)
                code_candidates = [c for c in {code_from_sync, norm_code} if c]
                produto = Product.objects.filter(code__in=code_candidates).first()
                if not produto:
                    numeric = norm_code if norm_code and norm_code.isdigit() else None
                    if numeric:
                        try:
                            produto = Product.objects.filter(pk=int(numeric)).first()
                        except Exception:
                            produto = None
        if produto:
            return produto

    # 1b) Se veio código (e não PLU), tente mapear via tabela de sync (codigo -> produto)
    if not produto and normalized:
        code_candidates = {raw, normalized}
        digits = "".join(ch for ch in normalized if ch.isdigit())
        if digits:
            code_candidates.add(digits)
            stripped = digits.lstrip("0") or "0"
            code_candidates.add(stripped)

        psync = ProdutoSync.objects.filter(codigo__in=[c for c in code_candidates if c]).order_by(produto_sync_ordering).first()
        if psync:
            # Se a sync tem PLU, reaproveita a lógica acima
            plu_from_sync = str(psync.plu).strip() if psync.plu else None
            if plu_from_sync:
                plu_digits = "".join(ch for ch in plu_from_sync if ch.isdigit())
                plu_stripped = plu_digits.lstrip("0") or ("0" if plu_digits else None)
                plu_candidates = [plu_from_sync]
                for cand in (plu_digits, plu_stripped):
                    if cand and cand not in plu_candidates:
                        plu_candidates.append(cand)
                produto = Product.objects.filter(plu_code__in=plu_candidates).first()
            if not produto and psync.codigo:
                code_from_sync = str(psync.codigo).strip()
                norm_code = Product.normalize_code(code_from_sync)
                code_lookup = [c for c in {code_from_sync, norm_code} if c]
                produto = Product.objects.filter(code__in=code_lookup).first()
                if not produto and norm_code and norm_code.isdigit():
                    try:
                        produto = Product.objects.filter(pk=int(norm_code)).first()
                    except Exception:
                        produto = None
            if produto:
                return produto

    # 2) PK numérico
    if not produto and normalized and normalized.isdigit():
        produto = Product.objects.filter(pk=int(normalized)).first()
    # 3) Código interno
    if not produto and normalized:
        produto = Product.objects.filter(code=normalized).first()
    if not produto:
        raise HTTPException(400, f"Produto não encontrado: {codigo_produto}")
    return produto


def _create_pedido_sync(
    payload: PedidoIn,
    loja_codigo: str,
    token_vendor_code: Optional[str] = None,
):
    try:
        itens_payload = payload.itens
        if not itens_payload:
            raise HTTPException(400, "Lista de itens não pode ser vazia")

        cliente = _resolve_cliente(payload.cliente_id, loja_codigo)

        itens_resolvidos = []
        total_calculado = Decimal("0")
        for item in itens_payload:
            produto = _resolve_produto(item.codigo_produto)
            quantidade = Decimal(item.quantidade)
            valor_unitario = Decimal(item.valor_unitario)
            total_calculado += quantidade * valor_unitario
            itens_resolvidos.append((produto, quantidade, valor_unitario))

        if abs(total_calculado - Decimal(payload.total)) > Decimal("0.01"):
            raise HTTPException(
                400,
                f"Total inconsistente: recebido {payload.total}, calculado {total_calculado}",
            )

        pagamento_status = (payload.pagamento_status or Pedido.PaymentStatus.AGUARDANDO).strip()
        if not pagamento_status:
            pagamento_status = Pedido.PaymentStatus.AGUARDANDO
        frete_modalidade = (payload.frete_modalidade or Pedido.FreightMode.SEM_FRETE).strip() or Pedido.FreightMode.SEM_FRETE
        forma_pagamento = (payload.forma_pagamento or "").strip()
        status_val = payload.status.strip() if payload.status else None
        if not status_val:
            status_val = (
                Pedido.Status.EM_SEPARACAO
                if pagamento_status in (Pedido.PaymentStatus.PAGO_AVISTA, Pedido.PaymentStatus.FATURA_A_VENCER)
                else Pedido.Status.PRE_VENDA
            )
        vendedor_codigo = (payload.vendedor_codigo or token_vendor_code or "").strip()
        vendedor_nome = (payload.vendedor_nome or "").strip()
        if not vendedor_codigo and token_vendor_code:
            vendedor_codigo = token_vendor_code
        if vendedor_codigo and (not vendedor_nome or vendedor_nome.strip().lower().startswith("loja")):
            qs = ClienteSync.objects.filter(vendedor_codigo=vendedor_codigo)
            if loja_codigo:
                qs = qs.filter(loja_codigo=loja_codigo)
            match = (
                qs.exclude(vendedor_nome__isnull=True)
                .exclude(vendedor_nome="")
                .order_by("vendedor_nome")
                .first()
            )
            if match:
                vendedor_nome = match.vendedor_nome or vendedor_nome

        # Idempotência: evita duplicar se já recebemos o mesmo pedido recentemente.
        window_start = dj_timezone.now() - timedelta(minutes=10)
        existente = (
            Pedido.objects.filter(
                cliente=cliente,
                data_criacao=payload.data_criacao,
                total=payload.total,
                data_recebimento__gte=window_start,
            )
            .order_by("-id")
            .first()
        )
        if existente:
            return existente, False

        loja_field = _get_pedido_loja_field()
        if not loja_field:
            raise HTTPException(500, "Modelo Pedido sem loja_codigo")

        with transaction.atomic():
            pedido_kwargs = {
                "data_criacao": payload.data_criacao,
                "total": payload.total,
                "cliente": cliente,
                "status": status_val,
                "pagamento_status": pagamento_status,
                "forma_pagamento": forma_pagamento,
                "frete_modalidade": frete_modalidade,
                "vendedor_codigo": vendedor_codigo,
                "vendedor_nome": vendedor_nome,
                loja_field: loja_codigo,
            }
            pedido = Pedido.objects.create(**pedido_kwargs)
            ItemPedido.objects.bulk_create(
                [
                    ItemPedido(
                        pedido=pedido,
                        produto=prod,
                        quantidade=quant,
                        valor_unitario=valor,
                        loja_codigo=loja_codigo,
                    )
                    for (prod, quant, valor) in itens_resolvidos
                ]
            )
        return pedido, True
    except Exception:
        logger.exception("Erro ao criar pedido via API (payload capturado)")
        raise


def _pedido_to_dict(pedido: Pedido):
    itens_out = []
    for item in pedido.itens.all():
        qty = item.quantidade or Decimal("0")
        unit = item.valor_unitario or Decimal("0")
        itens_out.append(
            {
                "produto_id": item.produto_id,
                "produto_codigo": item.produto.code if hasattr(item.produto, "code") else None,
                "produto_nome": getattr(item.produto, "name", None) or str(item.produto),
                "quantidade": float(qty),
                "valor_unitario": float(unit),
                "subtotal": float(qty * unit),
            }
        )

    return {
        "id": pedido.id,
        "cliente_id": pedido.cliente_id,
        "cliente_nome": str(pedido.cliente),
        "data_criacao": pedido.data_criacao,
        "data_recebimento": pedido.data_recebimento,
        "total": float(pedido.total),
        "status": pedido.status,
        "status_display": pedido.get_status_display(),
        "pagamento_status": pedido.pagamento_status,
        "pagamento_status_display": pedido.get_pagamento_status_display(),
        "forma_pagamento": pedido.forma_pagamento,
        "frete_modalidade": pedido.frete_modalidade,
        "frete_modalidade_display": pedido.get_frete_modalidade_display(),
        "vendedor_codigo": pedido.vendedor_codigo,
        "vendedor_nome": pedido.vendedor_nome,
        "itens": itens_out,
    }


def _get_pedido_loja_field() -> Optional[str]:
    for field in Pedido._meta.fields:
        if field.name in ("loja_codigo", "loja"):
            return field.name
    return None


def _listar_pedidos_sync(
    limit: int,
    cliente_id: Optional[str],
    status: Optional[str],
    loja_codigo: str,
):
    loja_field = _get_pedido_loja_field()
    if not loja_field:
        raise HTTPException(500, "Modelo Pedido sem loja_codigo")
    qs = Pedido.objects.select_related("cliente").prefetch_related("itens__produto").order_by("-data_recebimento")
    qs = qs.filter(**{loja_field: loja_codigo})
    if cliente_id:
        try:
            cliente = _resolve_cliente(cliente_id, loja_codigo)
            qs = qs.filter(cliente=cliente)
        except HTTPException:
            qs = qs.none()
    if status:
        qs = qs.filter(status=status)
    return [_pedido_to_dict(p) for p in qs[:limit]]


def _get_pedido_sync(pedido_id: int, loja_codigo: str):
    loja_field = _get_pedido_loja_field()
    if not loja_field:
        raise HTTPException(500, "Modelo Pedido sem loja_codigo")
    pedido = (
        Pedido.objects.select_related("cliente")
        .prefetch_related("itens__produto")
        .filter(pk=pedido_id, **{loja_field: loja_codigo})
        .first()
    )
    if not pedido:
        raise HTTPException(404, "Pedido não encontrado")
    return _pedido_to_dict(pedido)


@router.post("/pedidos", tags=["pedidos"])
async def criar_pedido(
    payload: PedidoIn,
    token: dict = Depends(require_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    pedido, created = await run_in_threadpool(
        _create_pedido_sync,
        payload,
        loja_codigo,
        token.get("vendor_code"),
    )
    status_code = 201 if created else 200
    mensagem = "Pedido criado com sucesso" if created else "Pedido já recebido recentemente"
    return JSONResponse(
        {
            "id": pedido.id,
            "status": pedido.status,
            "pagamento_status": pedido.pagamento_status,
            "forma_pagamento": pedido.forma_pagamento,
            "frete_modalidade": pedido.frete_modalidade,
            "vendedor_codigo": pedido.vendedor_codigo,
            "vendedor_nome": pedido.vendedor_nome,
            "mensagem": mensagem,
            "created": created,
        },
        status_code=status_code,
    )


@router.get("/pedidos", tags=["pedidos"])
async def listar_pedidos(
    limit: int = Query(100, ge=1, le=500),
    cliente_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    token: dict = Depends(require_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    if status and status not in PEDIDO_STATUS_VALUES:
        raise HTTPException(400, f"Status inválido. Opções: {sorted(PEDIDO_STATUS_VALUES)}")
    return await run_in_threadpool(_listar_pedidos_sync, limit, cliente_id, status, loja_codigo)


@router.get("/pedidos/{pedido_id}", tags=["pedidos"])
async def detalhar_pedido(
    pedido_id: int,
    token: dict = Depends(require_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    return await run_in_threadpool(_get_pedido_sync, pedido_id, loja_codigo)


@router.post("/pedidos-venda", tags=["pedidos"])
async def criar_pedido_venda(
    payload: PedidoIn,
    token: dict = Depends(require_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    pedido, created = await run_in_threadpool(
        _create_pedido_sync,
        payload,
        loja_codigo,
        token.get("vendor_code"),
    )
    if created:
        return {
            "id": pedido.id,
            "status": pedido.status,
            "pagamento_status": pedido.pagamento_status,
            "forma_pagamento": pedido.forma_pagamento,
            "frete_modalidade": pedido.frete_modalidade,
            "vendedor_codigo": pedido.vendedor_codigo,
            "vendedor_nome": pedido.vendedor_nome,
        }
    return {"id": pedido.id, "status": pedido.status}


@router.get("/pedidos-venda", tags=["pedidos"])
async def listar_pedidos_venda(
    limit: int = 50,
    cliente_id: Optional[str] = None,
    status: Optional[str] = None,
    token: dict = Depends(require_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    return await run_in_threadpool(_listar_pedidos_sync, limit, cliente_id, status, loja_codigo)


@router.get("/pedidos-venda/{pedido_id}", tags=["pedidos"])
async def detalhar_pedido_venda(
    pedido_id: int,
    token: dict = Depends(require_jwt),
    loja_codigo: str = Depends(require_tenant),
):
    return await run_in_threadpool(_get_pedido_sync, pedido_id, loja_codigo)


app.include_router(router)
app.include_router(images_router)
app.include_router(clientes_router, dependencies=[Depends(require_jwt)])
app.include_router(auth_router)


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "9000"))
    reload = os.getenv("API_RELOAD", "false").lower() in ("1", "true", "yes", "on")
    uvicorn.run("erp_api:app", host=host, port=port, reload=reload)
