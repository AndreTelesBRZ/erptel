import os
from decimal import Decimal
from typing import List, Optional

import psycopg2
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ProdutoSync(BaseModel):
    codigo: str
    descricao_completa: str
    referencia: Optional[str] = None
    secao: Optional[str] = None
    grupo: Optional[str] = None
    subgrupo: Optional[str] = None
    unidade: Optional[str] = None
    ean: Optional[str] = None
    plu: str
    preco_normal: Decimal = Decimal("0")
    preco_promocao1: Decimal = Decimal("0")
    preco_promocao2: Decimal = Decimal("0")
    estoque_disponivel: Decimal = Decimal("0")
    custo: Decimal = Decimal("0")
    loja: str
    row_hash: str


class ClienteSync(BaseModel):
    cliente_codigo: str
    cliente_status: Optional[int] = None
    cliente_razao_social: str
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


def get_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        dbname=os.getenv("POSTGRES_DB", "erptel"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "minhasenha")
    )


@router.post("/api/products/sync")
def sync_produtos(produtos: List[ProdutoSync]):
    conn = get_conn()
    cur = conn.cursor()

    sql = """
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
            %(codigo)s, %(descricao_completa)s, %(referencia)s, %(secao)s, %(grupo)s,
            %(subgrupo)s, %(unidade)s, %(ean)s, %(plu)s, %(preco_normal)s,
            %(preco_promocao1)s, %(preco_promocao2)s, %(estoque_disponivel)s, %(loja)s,
            %(row_hash)s, %(custo)s, NOW()
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
           preco_normal = EXCLUDED.preco_normal,
           preco_promocao1 = EXCLUDED.preco_promocao1,
           preco_promocao2 = EXCLUDED.preco_promocao2,
           estoque_disponivel = EXCLUDED.estoque_disponivel,
           loja = EXCLUDED.loja,
           row_hash = EXCLUDED.row_hash,
           custo = EXCLUDED.custo,
           updated_at = NOW();
    """

    try:
        for p in produtos:
            cur.execute(sql, p.dict())
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return {"status": "ok", "total": len(produtos)}


@router.post("/api/clientes/sync")
def sync_clientes(clientes: List[ClienteSync]):
    conn = get_conn()
    cur = conn.cursor()

    sql = """
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
            vendedor_codigo,
            vendedor_nome,
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
            %(vendedor_codigo)s,
            %(vendedor_nome)s,
            NOW()
        )
        ON CONFLICT (cliente_codigo) DO UPDATE SET
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
            vendedor_codigo = EXCLUDED.vendedor_codigo,
            vendedor_nome = EXCLUDED.vendedor_nome,
            updated_at = NOW();
    """

    try:
        for c in clientes:
            cur.execute(sql, c.dict())
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return {
        "status": "ok",
        "total": len(clientes)
    }
