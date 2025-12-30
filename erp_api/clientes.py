import os
import psycopg2
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/clientes", tags=["clientes"])
logger = logging.getLogger("erp_api.clientes")
CLIENTES_LOJA_GLOBAL = (os.getenv("CLIENTES_LOJA_GLOBAL") or "").strip().lower() in ("1", "true", "yes", "on")
CLIENTES_LOJA_GLOBAL_CODE = (os.getenv("CLIENTES_LOJA_GLOBAL_CODE") or "00000").strip() or "00000"


class ClienteSync(BaseModel):
    cliente_codigo: str
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
    ultima_venda_data: Optional[str] = None
    ultima_venda_valor: Optional[float] = None


_CLIENTE_COLUMNS = [
    "cliente_status",
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
    "limite_credito",
    "row_hash",
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


def _table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s);", (table_name,))
    return cur.fetchone()[0] is not None


def _has_unique_vendedores_index(cur) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND tablename = 'erp_clientes_vendedores'
          AND (
              indexdef ILIKE '%(cliente_codigo, loja_codigo)%'
              OR indexdef ILIKE '%(loja_codigo, cliente_codigo)%'
          )
        LIMIT 1;
        """
    )
    return cur.fetchone() is not None


def _get_primary_key_columns(cur) -> list[str]:
    cur.execute(
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN unnest(i.indkey) WITH ORDINALITY AS cols(attnum, ord) ON TRUE
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = cols.attnum
        WHERE t.relname = 'erp_clientes_vendedores'
          AND i.indisprimary
        ORDER BY cols.ord;
        """
    )
    return [row[0] for row in cur.fetchall()]


def _has_duplicate_vinculos(cur) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM erp_clientes_vendedores
        GROUP BY cliente_codigo, loja_codigo
        HAVING COUNT(*) > 1
        LIMIT 1;
        """
    )
    return cur.fetchone() is not None


def _ensure_vendedores_columns(cur) -> None:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'erp_clientes_vendedores';
        """
    )
    cols = {row[0] for row in cur.fetchall()}
    if "ultima_venda_data" not in cols:
        cur.execute("ALTER TABLE erp_clientes_vendedores ADD COLUMN ultima_venda_data TIMESTAMP NULL;")
    if "ultima_venda_valor" not in cols:
        cur.execute("ALTER TABLE erp_clientes_vendedores ADD COLUMN ultima_venda_valor NUMERIC(14,2) NULL;")
    if "limite_credito" not in cols:
        cur.execute("ALTER TABLE erp_clientes_vendedores ADD COLUMN limite_credito NUMERIC(14,2) NULL;")
    if "row_hash" not in cols:
        cur.execute("ALTER TABLE erp_clientes_vendedores ADD COLUMN row_hash TEXT NULL;")


def _ensure_clientes_columns(cur) -> None:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'erp_clientes';
        """
    )
    cols = {row[0] for row in cur.fetchall()}
    if "limite_credito" not in cols:
        cur.execute("ALTER TABLE erp_clientes ADD COLUMN limite_credito NUMERIC(14,2) NULL;")
    if "row_hash" not in cols:
        cur.execute("ALTER TABLE erp_clientes ADD COLUMN row_hash TEXT NULL;")


def _ensure_unique_vendedores_key(cur) -> None:
    if _has_unique_vendedores_index(cur):
        return
    pk_cols = _get_primary_key_columns(cur)
    if pk_cols == ["cliente_codigo", "loja_codigo"]:
        return
    if pk_cols and pk_cols != ["cliente_codigo"]:
        logger.warning(
            "erp_clientes_vendedores: chave primaria existente (%s); ajuste manual necessario.",
            ",".join(pk_cols),
        )
        return
    if _has_duplicate_vinculos(cur):
        logger.warning(
            "erp_clientes_vendedores: existem duplicidades (cliente_codigo, loja_codigo); "
            "chave composta não aplicada."
        )
        return
    if pk_cols == ["cliente_codigo"]:
        cur.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'erp_clientes_vendedores'::regclass
              AND contype = 'p';
            """
        )
        row = cur.fetchone()
        if row:
            cur.execute(f'ALTER TABLE erp_clientes_vendedores DROP CONSTRAINT "{row[0]}";')
    cur.execute(
        """
        ALTER TABLE erp_clientes_vendedores
        ADD CONSTRAINT erp_clientes_vendedores_pkey
        PRIMARY KEY (cliente_codigo, loja_codigo);
        """
    )


@router.post("/sync")
def sync_clientes(clientes: List[ClienteSync], request: Request):
    conn = None
    cur = None
    loja_codigo = getattr(request.state, "loja_codigo", None)
    if not loja_codigo:
        raise HTTPException(status_code=500, detail="Loja não resolvida")

    sql_cadastro = """
        INSERT INTO erp_clientes (
            cliente_codigo,
            cliente_status,
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
            limite_credito,
            row_hash,
            updated_at
        )
        VALUES (
            %(cliente_codigo)s,
            %(cliente_status)s,
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
            %(limite_credito)s,
            %(row_hash)s,
            NOW()
        )
        ON CONFLICT (cliente_codigo)
        DO UPDATE SET
            cliente_status = EXCLUDED.cliente_status,
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
            limite_credito = EXCLUDED.limite_credito,
            row_hash = EXCLUDED.row_hash,
            updated_at = NOW();
    """

    sql_vinculo = """
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
            limite_credito,
            row_hash,
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
            %(limite_credito)s,
            %(row_hash)s,
            %(vendedor_codigo)s,
            %(vendedor_nome)s,
            %(ultima_venda_data)s,
            %(ultima_venda_valor)s,
            %(loja_codigo)s,
            NOW()
        )
        ON CONFLICT (cliente_codigo, loja_codigo)
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
            limite_credito = EXCLUDED.limite_credito,
            row_hash = EXCLUDED.row_hash,
            vendedor_codigo = EXCLUDED.vendedor_codigo,
            vendedor_nome = EXCLUDED.vendedor_nome,
            ultima_venda_data = EXCLUDED.ultima_venda_data,
            ultima_venda_valor = EXCLUDED.ultima_venda_valor,
            updated_at = NOW();
    """

    sql_vinculo_single_key = """
        INSERT INTO erp_clientes_vendedores (
            cliente_codigo,
            cliente_status,
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
            limite_credito,
            row_hash,
            vendedor_codigo,
            vendedor_nome,
            ultima_venda_data,
            ultima_venda_valor,
            loja_codigo,
            updated_at
        )
        SELECT
            %(cliente_codigo)s,
            %(cliente_status)s,
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
            %(limite_credito)s,
            %(row_hash)s,
            %(vendedor_codigo)s,
            %(vendedor_nome)s,
            %(ultima_venda_data)s,
            %(ultima_venda_valor)s,
            %(loja_codigo)s,
            NOW()
        ON CONFLICT (cliente_codigo)
        DO UPDATE SET
            cliente_status = EXCLUDED.cliente_status,
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
            limite_credito = EXCLUDED.limite_credito,
            row_hash = EXCLUDED.row_hash,
            vendedor_codigo = EXCLUDED.vendedor_codigo,
            vendedor_nome = EXCLUDED.vendedor_nome,
            ultima_venda_data = EXCLUDED.ultima_venda_data,
            ultima_venda_valor = EXCLUDED.ultima_venda_valor,
            loja_codigo = EXCLUDED.loja_codigo,
            updated_at = NOW()
        RETURNING (xmax = 0) AS inserted;
    """

    try:
        conn = get_conn()
        cur = conn.cursor()
        _ensure_vendedores_columns(cur)
        _ensure_unique_vendedores_key(cur)
        has_erp_clientes = _table_exists(cur, "public.erp_clientes")
        if has_erp_clientes:
            _ensure_clientes_columns(cur)
        has_unique_vinculo = _has_unique_vendedores_index(cur)

        for c in clientes:
            data = c.dict()
            for key in _CLIENTE_COLUMNS:
                data.setdefault(key, None)
            if CLIENTES_LOJA_GLOBAL:
                data["loja_codigo"] = CLIENTES_LOJA_GLOBAL_CODE
            else:
                data["loja_codigo"] = loja_codigo
            if has_erp_clientes:
                cur.execute(sql_cadastro, data)
            if has_unique_vinculo:
                cur.execute(sql_vinculo, data)
            else:
                cur.execute(sql_vinculo_single_key, data)
                row = cur.fetchone()
                if row and not row[0]:
                    logger.info(
                        "Vínculo cliente atualizado via conflito (cliente_codigo=%s loja_codigo=%s)",
                        data.get("cliente_codigo"),
                        data.get("loja_codigo"),
                    )

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
