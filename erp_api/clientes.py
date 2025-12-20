import os
import psycopg2
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/clientes", tags=["clientes"])
logger = logging.getLogger("erp_api.clientes")


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
def sync_clientes(clientes: List[ClienteSync]):
    conn = None
    cur = None

    sql = """
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
            updated_at = NOW();
    """

    try:
        conn = get_conn()
        cur = conn.cursor()

        for c in clientes:
            data = c.dict()
            for key in _CLIENTE_COLUMNS:
                data.setdefault(key, None)
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
