from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, field_validator
from typing import List, Optional
import asyncpg
import os
import base64
import hashlib
import secrets
import hmac
import jwt
import django
from decimal import Decimal
from datetime import datetime, timedelta, timezone as dt_timezone
from django.utils import timezone as dj_timezone
from erp_api.clientes import router as clientes_router
import logging
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")
django.setup()

from clients.models import Client, ClienteSync
from products.models import Product, ProdutoSync
from api.models import PlanoPagamentoCliente, Loja
from sales.models import Pedido, ItemPedido
from django.db import transaction, models
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

app = FastAPI()
bearer_scheme = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/api")
auth_router = APIRouter(prefix="/auth", tags=["auth"])

# -----------------------------------
# CORS liberado
# -----------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        "PLADES": plan.descricao or "",
        "PLAENT": plan.entrada_percentual,
        "PLAINTPRI": plan.intervalo_primeira_parcela,
        "PLAINTPAR": plan.intervalo_parcelas,
        "PLANUMPAR": plan.quantidade_parcelas,
        "PLAVLRMIN": plan.valor_minimo,
        "PLAVLRACR": plan.valor_acrescimo,
    }


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


async def _resolve_vendor_for_username(username: str) -> Optional[dict]:
    name = (username or "").strip().lower()
    if not name:
        return None
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT vendedor_codigo, vendedor_nome
            FROM erp_clientes_vendedores
            WHERE lower(vendedor_nome) = $1
            ORDER BY vendedor_codigo
            LIMIT 1;
            """,
            name,
        )
    if row:
        return {"vendor_code": row["vendedor_codigo"], "vendor_name": row["vendedor_nome"]}
    return None


async def _resolve_vendor_by_code(vendor_code: Optional[str]) -> Optional[dict]:
    code = (vendor_code or "").strip()
    if not code:
        return None
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT vendedor_codigo, vendedor_nome
            FROM erp_clientes_vendedores
            WHERE vendedor_codigo = $1
            ORDER BY vendedor_nome
            LIMIT 1;
            """,
            code,
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
    CLICOD: str
    PLACOD: str
    PLADES: Optional[str] = None
    PLAENT: Optional[Decimal] = None
    PLAINTPRI: Optional[int] = None
    PLAINTPAR: Optional[int] = None
    PLANUMPAR: Optional[int] = None
    PLAVLRMIN: Optional[Decimal] = None
    PLAVLRACR: Optional[Decimal] = None


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


async def require_jwt(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    if DISABLE_API_AUTH:
        return {"id": 0, "username": "auth_disabled"}
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
        raise HTTPException(403, "Token inválido")

    user_id = payload.get("sub")
    username = payload.get("username")
    if not user_id:
        raise HTTPException(403, "Token inválido")

    pool = _get_auth_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, is_active FROM api_users WHERE id = $1;",
            int(user_id),
        )
    if not row or not row["is_active"]:
        raise HTTPException(403, "Usuário inativo ou não encontrado")

    return {
        "id": row["id"],
        "username": row["username"],
        "token_username": username,
        "vendor_code": payload.get("vendor_code"),
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
# -----------------------------------
# LISTAR PRODUTOS (tabela já existente)
# -----------------------------------
@app.get("/api/products", tags=["produtos"])
async def listar_produtos(token: dict = Depends(require_jwt)):
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM erp_produtos_sync ORDER BY codigo;")
        return [dict(r) for r in rows]


@app.get("/api/produtos-sync", tags=["produtos"])
async def listar_produtos_sync(
    q: Optional[str] = None,
    codigo: Optional[str] = None,
    plu: Optional[str] = None,
    ean: Optional[str] = None,
    loja: Optional[str] = None,
    token: dict = Depends(require_jwt),
):
    clauses = []
    params = []

    if codigo:
        params.append(codigo)
        clauses.append(f"codigo = ${len(params)}")
    if plu:
        params.append(plu)
        clauses.append(f"plu = ${len(params)}")
    if ean:
        params.append(ean)
        clauses.append(f"ean = ${len(params)}")
    if loja:
        params.append(loja)
        clauses.append(f"loja = ${len(params)}")
    if q:
        params.append(f"%{q}%")
        clauses.append(
            f"(descricao_completa ILIKE ${len(params)} OR referencia ILIKE ${len(params)} OR codigo ILIKE ${len(params)})"
        )

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM erp_produtos_sync {where_sql} ORDER BY codigo;"

    pool = _get_data_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


@app.get("/api/produtos-sync/{codigo}", tags=["produtos"])
async def produto_por_codigo(codigo: str, token: dict = Depends(require_jwt)):
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM erp_produtos_sync WHERE codigo = $1;",
            codigo,
        )
    if not row:
        raise HTTPException(404, "Produto não encontrado")
    return dict(row)

# -----------------------------------
# BUSCAR POR PLU
# -----------------------------------
@app.get("/api/products/{plu}", tags=["produtos"])
async def produto_por_plu(plu: str, token: dict = Depends(require_jwt)):
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM erp_produtos_sync WHERE plu = $1;",
            plu,
        )

    if not row:
        raise HTTPException(404, "Produto não encontrado")
    return dict(row)


# -----------------------------------
# BUSCA POR DESCRIÇÃO
# -----------------------------------
@app.get("/api/products/search", tags=["produtos"])
async def buscar_produto(q: str, token: dict = Depends(require_jwt)):
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
                SELECT * FROM erp_produtos_sync
                WHERE descricao_completa ILIKE $1
                LIMIT 50;
            """,
            f"%{q}%",
        )
        return [dict(r) for r in rows]


# -----------------------------------
# SINCRONIZAÇÃO DE PRODUTOS
# -----------------------------------
@app.post("/api/products/sync", tags=["produtos"])
async def sync_products(produtos: List[ProdutoSyncIn], token: dict = Depends(require_jwt)):
    pool = _get_data_pool()

    insert_sql = """
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
            row_hash,
            custo,
            updated_at
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9,
            $10, $11, $12, $13, $14, $15, $16, NOW()
        )
        ON CONFLICT ON CONSTRAINT erp_produtos_sync_plu_loja_key DO UPDATE SET
            codigo = EXCLUDED.codigo,
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
            loja = EXCLUDED.loja,
            row_hash = EXCLUDED.row_hash,
            custo = EXCLUDED.custo,
            updated_at = NOW();
    """

    payload = [
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
            p.loja,
            p.row_hash,
            p.custo,
        )
        for p in produtos
    ]

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(insert_sql, payload)
        return {"status": "ok", "total": len(produtos)}

    except Exception as e:
        raise HTTPException(500, f"Erro ao sincronizar: {e}") from e


# -----------------------------------
# CLIENTES
# -----------------------------------
@app.get("/api/clientes", tags=["clientes"])
async def listar_clientes(
    page: int = Query(1, ge=1),
    page_size: Optional[int] = Query(None, ge=1),
    token: dict = Depends(require_jwt),
):
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM erp_clientes_vendedores;")
        if page_size:
            offset = (page - 1) * page_size
            rows = await conn.fetch(
                """
                SELECT *
                FROM erp_clientes_vendedores
                ORDER BY cliente_codigo
                OFFSET $1 LIMIT $2;
                """,
                offset,
                page_size,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT *
                FROM erp_clientes_vendedores
                ORDER BY cliente_codigo;
                """
            )

    data = [dict(r) for r in rows]
    response = {
        "total": total,
        "data": data,
    }
    if page_size:
        response["page"] = page
        response["page_size"] = page_size
    return response


@app.get("/api/clientes/lista", tags=["clientes"])
async def listar_clientes_lista(token: dict = Depends(require_jwt)):
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM erp_clientes_vendedores
            ORDER BY cliente_codigo;
            """
        )
    return [dict(r) for r in rows]


@app.get("/api/clientes/lista", tags=["clientes"])
async def listar_clientes_lista(token: dict = Depends(require_jwt)):
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM erp_clientes_vendedores
            ORDER BY cliente_codigo;
            """
        )
    return [dict(r) for r in rows]


@app.get("/api/clientes/{cliente_codigo}", tags=["clientes"])
async def cliente_por_codigo(cliente_codigo: str, token: dict = Depends(require_jwt)):
    pool = _get_data_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM erp_clientes_vendedores
            WHERE cliente_codigo = $1;
            """,
            cliente_codigo,
        )
    if not row:
        raise HTTPException(404, "Cliente não encontrado")
    return dict(row)


@app.get("/api/clientes/search", tags=["clientes"])
async def buscar_cliente(q: str, token: dict = Depends(require_jwt)):
    pool = _get_data_pool()
    like = f"%{q}%"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM erp_clientes_vendedores
            WHERE cliente_razao_social ILIKE $1
               OR cliente_nome_fantasia ILIKE $1
               OR cliente_cnpj_cpf ILIKE $1
            """,
            like,
        )
    return [dict(r) for r in rows]


# -----------------------------------
# PLANOS DE PAGAMENTO (Postgres)
# -----------------------------------
def _sync_planos_pagamento_clientes(payload: List[PlanoPagamentoClienteIn]) -> int:
    now = dj_timezone.now()
    plans = [
        PlanoPagamentoCliente(
            cliente_codigo=item.CLICOD,
            plano_codigo=item.PLACOD,
            descricao=item.PLADES or "",
            entrada_percentual=item.PLAENT,
            intervalo_primeira_parcela=item.PLAINTPRI,
            intervalo_parcelas=item.PLAINTPAR,
            quantidade_parcelas=item.PLANUMPAR,
            valor_minimo=item.PLAVLRMIN,
            valor_acrescimo=item.PLAVLRACR,
            updated_at=now,
        )
        for item in payload
    ]
    if not plans:
        return 0
    PlanoPagamentoCliente.objects.bulk_create(
        plans,
        update_conflicts=True,
        unique_fields=["cliente_codigo", "plano_codigo"],
        update_fields=[
            "descricao",
            "entrada_percentual",
            "intervalo_primeira_parcela",
            "intervalo_parcelas",
            "quantidade_parcelas",
            "valor_minimo",
            "valor_acrescimo",
            "updated_at",
        ],
    )
    return len(plans)


@app.get("/api/planos-pagamento-cliente", tags=["planos_pagamento"])
async def listar_planos_pagamento_cliente(
    cliente_codigo: str = Query(...),
    token: dict = Depends(require_jwt),
):
    plans = await run_in_threadpool(
        lambda: list(
            PlanoPagamentoCliente.objects.filter(cliente_codigo=cliente_codigo).order_by("plano_codigo")
        )
    )
    data = [_plan_to_dict(plan) for plan in plans]
    return {"cliente_codigo": cliente_codigo, "total": len(data), "data": data}


@app.get("/api/planos-pagamento-cliente/{cliente_codigo}", tags=["planos_pagamento"])
async def listar_planos_pagamento_cliente_path(
    cliente_codigo: str,
    token: dict = Depends(require_jwt),
):
    plans = await run_in_threadpool(
        lambda: list(
            PlanoPagamentoCliente.objects.filter(cliente_codigo=cliente_codigo).order_by("plano_codigo")
        )
    )
    data = [_plan_to_dict(plan) for plan in plans]
    return {"cliente_codigo": cliente_codigo, "total": len(data), "data": data}


@app.post("/api/planos-pagamento-clientes/sync", tags=["planos_pagamento"])
async def sync_planos_pagamento_clientes(
    payload: List[PlanoPagamentoClienteIn],
    token: dict = Depends(require_jwt),
):
    total = await run_in_threadpool(_sync_planos_pagamento_clientes, payload)
    return {"status": "ok", "total": total}


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
):
    def _fetch():
        qs = Loja.objects.all().order_by("codigo")
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
):
    loja = await run_in_threadpool(lambda: Loja.objects.filter(codigo=loja_codigo).first())
    if not loja:
        raise HTTPException(404, "Loja não encontrada")
    return _loja_to_dict(loja)


@app.post("/api/lojas/sync", tags=["lojas"])
async def sync_lojas(
    payload: List[LojaIn],
    token: dict = Depends(require_jwt),
):
    total = await run_in_threadpool(_sync_lojas, payload)
    return {"status": "ok", "total": total}


# -----------------------------------
# ROTA RAIZ
# -----------------------------------
@app.get("/")
async def root(token: dict = Depends(require_jwt)):
    return {"status": "API funcionando", "user_id": token.get("id")}


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


@auth_router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
    user = await _get_user_by_credentials(payload.username.strip(), payload.password)
    if not user:
        raise HTTPException(401, "Usuário ou senha inválidos", headers={"WWW-Authenticate": "Bearer"})
    vendor = await _resolve_vendor_by_code(user.get("vendor_code"))
    # Fallback por nome apenas se não houver vendor_code cadastrado
    if not vendor:
        vendor = await _resolve_vendor_for_username(payload.username)
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


@app.post("/api/login", tags=["auth"])
async def login_alias(payload: LoginRequest):
    return await login(payload)


@auth_router.post("/users", response_model=UserOut, dependencies=[Depends(require_admin)])
async def create_user(payload: UserCreateRequest):
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

    vendor = await _resolve_vendor_by_code(row.get("vendor_code"))
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
# PEDIDOS
# -----------------------------------
def _resolve_cliente(cliente_id: str) -> Client:
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
    sync_entry = ClienteSync.objects.filter(cliente_codigo=client_code).first()
    if not sync_entry and client_code.isdigit():
        stripped = client_code.lstrip("0")
        if stripped:
            sync_entry = ClienteSync.objects.filter(cliente_codigo=stripped).first()

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
            # ProdutoSync não possui campo de timestamp; usamos um fallback determinístico
            psync = ProdutoSync.objects.filter(plu__in=plu_candidates).order_by("-codigo").first()
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

        # ProdutoSync não possui campo de timestamp; usamos um fallback determinístico
        psync = ProdutoSync.objects.filter(codigo__in=[c for c in code_candidates if c]).order_by("-codigo").first()
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


def _create_pedido_sync(payload: PedidoIn, token_vendor_code: Optional[str] = None):
    try:
        itens_payload = payload.itens
        if not itens_payload:
            raise HTTPException(400, "Lista de itens não pode ser vazia")

        cliente = _resolve_cliente(payload.cliente_id)

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

        with transaction.atomic():
            pedido = Pedido.objects.create(
                data_criacao=payload.data_criacao,
                total=payload.total,
                cliente=cliente,
                status=status_val,
                pagamento_status=pagamento_status,
                forma_pagamento=forma_pagamento,
                frete_modalidade=frete_modalidade,
                vendedor_codigo=vendedor_codigo,
                vendedor_nome=vendedor_nome,
            )
            ItemPedido.objects.bulk_create(
                [
                    ItemPedido(
                        pedido=pedido,
                        produto=prod,
                        quantidade=quant,
                        valor_unitario=valor,
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


def _listar_pedidos_sync(limit: int, cliente_id: Optional[str], status: Optional[str]):
    qs = Pedido.objects.select_related("cliente").prefetch_related("itens__produto").order_by("-data_recebimento")
    if cliente_id:
        try:
            cliente = _resolve_cliente(cliente_id)
            qs = qs.filter(cliente=cliente)
        except HTTPException:
            qs = qs.none()
    if status:
        qs = qs.filter(status=status)
    return [_pedido_to_dict(p) for p in qs[:limit]]


def _get_pedido_sync(pedido_id: int):
    pedido = (
        Pedido.objects.select_related("cliente")
        .prefetch_related("itens__produto")
        .filter(pk=pedido_id)
        .first()
    )
    if not pedido:
        raise HTTPException(404, "Pedido não encontrado")
    return _pedido_to_dict(pedido)


@router.post("/pedidos", tags=["pedidos"])
async def criar_pedido(payload: PedidoIn, token: dict = Depends(require_jwt)):
    pedido, created = await run_in_threadpool(_create_pedido_sync, payload, token.get("vendor_code"))
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
):
    if status and status not in PEDIDO_STATUS_VALUES:
        raise HTTPException(400, f"Status inválido. Opções: {sorted(PEDIDO_STATUS_VALUES)}")
    return await run_in_threadpool(_listar_pedidos_sync, limit, cliente_id, status)


@router.get("/pedidos/{pedido_id}", tags=["pedidos"])
async def detalhar_pedido(pedido_id: int, token: dict = Depends(require_jwt)):
    return await run_in_threadpool(_get_pedido_sync, pedido_id)


@router.post("/pedidos-venda", tags=["pedidos"])
async def criar_pedido_venda(payload: PedidoIn, token: dict = Depends(require_jwt)):
    pedido, created = await run_in_threadpool(_create_pedido_sync, payload, token.get("vendor_code"))
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
):
    return await run_in_threadpool(_listar_pedidos_sync, limit, cliente_id, status)


@router.get("/pedidos-venda/{pedido_id}", tags=["pedidos"])
async def detalhar_pedido_venda(pedido_id: int, token: dict = Depends(require_jwt)):
    return await run_in_threadpool(_get_pedido_sync, pedido_id)


app.include_router(router)
app.include_router(clientes_router, dependencies=[Depends(require_jwt)])
app.include_router(auth_router)


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "9000"))
    reload = os.getenv("API_RELOAD", "false").lower() in ("1", "true", "yes", "on")
    uvicorn.run("erp_api:app", host=host, port=port, reload=reload)
