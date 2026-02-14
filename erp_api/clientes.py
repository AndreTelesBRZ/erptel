from datetime import datetime
import logging
import os
import psycopg2
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .tenant import determine_request_loja_codigo

router = APIRouter(prefix="/api/clientes", tags=["clientes"])
logger = logging.getLogger("erp_api.clientes")

DEFAULT_LOJA_CODIGO = os.getenv("DEFAULT_LOJA_CODIGO") or "00001"
LOJA_SQL_DEFAULT = DEFAULT_LOJA_CODIGO.replace("'", "''")


def _resolve_loja_codigo(request: Optional[Request]) -> str:
    codigo = determine_request_loja_codigo(request, DEFAULT_LOJA_CODIGO)
    if not codigo:
        logger.warning("Loja não identificada na requisição, usando padrão %s", DEFAULT_LOJA_CODIGO)
        codigo = DEFAULT_LOJA_CODIGO
    return codigo


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


class ClienteSync(BaseModel):
    cliente_codigo: str
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
    vendedor_codigo: Optional[str] = None
    vendedor_nome: Optional[str] = None
    ultima_venda_data: Optional[str] = None
    ultima_venda_valor: Optional[float] = None


_CLIENTE_COLUMNS = [
    "cliente_codigo",
    "cliente_razao_social",
    "cliente_nome_fantasia",
    "cliente_cnpj_cpf",
    "cliente_tipo_pf_pj",
    "cliente_endereco",
    "cliente_numero",
    "cliente_bairro",
    "cliente_cidade",
    "cliente_uf",
    "cliente_cep",
    "cliente_telefone1",
    "cliente_telefone2",
    "cliente_email",
    "cliente_inscricao_municipal",
    "vendedor_codigo",
    "vendedor_nome",
    "ultima_venda_data",
    "ultima_venda_valor",
]


def get_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        dbname=os.getenv("POSTGRES_DB", "erptel"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "minhasenha")
    )


@router.post("/sync")
def sync_clientes(clientes: List[ClienteSync], request: Request):
    conn = None
    cur = None

    sql = f"""
        INSERT INTO erp_clientes_vendedores (
            cliente_codigo,
            cliente_razao_social,
            cliente_nome_fantasia,
            cliente_cnpj_cpf,
            cliente_tipo_pf_pj,
            cliente_endereco,
            cliente_numero,
            cliente_bairro,
            cliente_cidade,
            cliente_uf,
            cliente_cep,
            cliente_telefone1,
            cliente_telefone2,
            cliente_email,
            cliente_inscricao_municipal,
            vendedor_codigo,
            vendedor_nome,
            ultima_venda_data,
            ultima_venda_valor,
            loja_codigo,
            updated_at
        )
        VALUES (
            %(cliente_codigo)s,
            %(cliente_razao_social)s,
            %(cliente_nome_fantasia)s,
            %(cliente_cnpj_cpf)s,
            %(cliente_tipo_pf_pj)s,
            %(cliente_endereco)s,
            %(cliente_numero)s,
            %(cliente_bairro)s,
            %(cliente_cidade)s,
            %(cliente_uf)s,
            %(cliente_cep)s,
            %(cliente_telefone1)s,
            %(cliente_telefone2)s,
            %(cliente_email)s,
            %(cliente_inscricao_municipal)s,
            %(vendedor_codigo)s,
            %(vendedor_nome)s,
            %(ultima_venda_data)s,
            %(ultima_venda_valor)s,
            COALESCE(%(loja_codigo)s, '{LOJA_SQL_DEFAULT}'),
            NOW()
        )
        ON CONFLICT (cliente_codigo)
        DO UPDATE SET
            cliente_razao_social = EXCLUDED.cliente_razao_social,
            cliente_nome_fantasia = EXCLUDED.cliente_nome_fantasia,
            cliente_cnpj_cpf = EXCLUDED.cliente_cnpj_cpf,
            cliente_tipo_pf_pj = EXCLUDED.cliente_tipo_pf_pj,
            cliente_endereco = EXCLUDED.cliente_endereco,
            cliente_numero = EXCLUDED.cliente_numero,
            cliente_bairro = EXCLUDED.cliente_bairro,
            cliente_cidade = EXCLUDED.cliente_cidade,
            cliente_uf = EXCLUDED.cliente_uf,
            cliente_cep = EXCLUDED.cliente_cep,
            cliente_telefone1 = EXCLUDED.cliente_telefone1,
            cliente_telefone2 = EXCLUDED.cliente_telefone2,
            cliente_email = EXCLUDED.cliente_email,
            cliente_inscricao_municipal = EXCLUDED.cliente_inscricao_municipal,
            vendedor_codigo = EXCLUDED.vendedor_codigo,
            vendedor_nome = EXCLUDED.vendedor_nome,
            ultima_venda_data = EXCLUDED.ultima_venda_data,
            ultima_venda_valor = EXCLUDED.ultima_venda_valor,
            loja_codigo = COALESCE(EXCLUDED.loja_codigo, '{LOJA_SQL_DEFAULT}'),
            updated_at = NOW();
    """

    try:
        conn = get_conn()
        cur = conn.cursor()

        loja_codigo = _resolve_loja_codigo(request)
        loja_codigo = loja_codigo.strip() if loja_codigo else DEFAULT_LOJA_CODIGO
        if not loja_codigo:
            loja_codigo = DEFAULT_LOJA_CODIGO
        for c in clientes:
            data = c.dict()
            for key in _CLIENTE_COLUMNS:
                data.setdefault(key, None)
            raw_data = data.get("ultima_venda_data")
            parsed_data = _parse_timestamp(raw_data)
            if raw_data and parsed_data is None:
                logger.warning(
                    "Data de última venda inválida para cliente %s: %r",
                    c.cliente_codigo,
                    raw_data,
                )
            data["ultima_venda_data"] = parsed_data
            data["loja_codigo"] = loja_codigo
            cur.execute(sql, data)

        conn.commit()
        return {"status": "ok", "total": len(clientes)}

    except Exception as exc:
        if conn:
            conn.rollback()
        logger.exception("Erro ao sincronizar clientes")
        # devolve 500 com detalhe curto
        raise HTTPException(status_code=500, detail=f"Erro ao sincronizar clientes: {exc}")

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
