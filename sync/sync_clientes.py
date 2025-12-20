import os
import pyodbc
import requests
import logging
from math import ceil
from fastapi import HTTPException
import traceback


# ==================================================
# CONFIGURAÇÕES
# ==================================================

# ---------- SQL SERVER ----------
SQLSERVER_CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=10.0.0.60,1433;"
    "DATABASE=SysacME;"
    "UID=sync_erptel;"
    "PWD=SenhaForte@2025;"
    "Encrypt=no;"
    "TrustServerCertificate=yes;"
)

# ---------- API ----------
API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:9000")
API_URL = os.getenv("API_CLIENTES_URL", f"{API_BASE}/api/clientes/sync")
API_LOGIN_URL = os.getenv("API_LOGIN_URL", f"{API_BASE}/auth/login")
API_USERNAME = os.getenv("API_USERNAME", "apiadmin")
API_PASSWORD = os.getenv("API_PASSWORD", "TroqueEstaSenha!")
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "60"))

# ---------- LOTE ----------
# Use BATCH_SIZE<=0 para enviar tudo em um único lote (sem limitação)
BATCH_SIZE = int(os.getenv("CLIENTES_BATCH_SIZE", "500"))

# ---------- LOG ----------
LOG_FILE = "/home/ubuntu/apps/Django/sync/sync.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | CLIENTES | %(levelname)s | %(message)s"
)

# ==================================================
# SQL ORIGEM
# ==================================================

SQL_SELECT = """
SELECT
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
    DATA_ULTIMA_VENDA AS ultima_venda_data,
    VALOR_ULTIMA_VENDA AS ultima_venda_valor
FROM dbo.vw_clientes_com_vendedor
"""

SQL_SELECT_FALLBACK = """
SELECT
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
    DATA_ULTIMA_VENDA AS ultima_venda_data,
    VALOR_ULTIMA_VENDA AS ultima_venda_valor
FROM dbo.vw_clientes_com_vendedor
"""

SQL_SELECT_FALLBACK_NO_STATUS_VENDOR = """
SELECT
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
    NULL AS vendedor_nome,
    DATA_ULTIMA_VENDA AS ultima_venda_data,
    VALOR_ULTIMA_VENDA AS ultima_venda_valor
FROM dbo.vw_clientes_com_vendedor
"""

SQL_SELECT_FALLBACK_NO_SALES = """
SELECT
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
    NULL AS ultima_venda_data,
    NULL AS ultima_venda_valor
FROM dbo.vw_clientes_com_vendedor
"""

SQL_SELECT_FALLBACK_NO_SALES_NO_VENDOR = """
SELECT
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
    NULL AS vendedor_nome,
    NULL AS ultima_venda_data,
    NULL AS ultima_venda_valor
FROM dbo.vw_clientes_com_vendedor
"""

# ==================================================
# FUNÇÕES
# ==================================================

def fetch_clientes():
    """Busca clientes no SQL Server"""
    conn = None
    cur = None

    try:
        conn = pyodbc.connect(SQLSERVER_CONN_STR, timeout=10)
        cur = conn.cursor()

        try:
            cur.execute(SQL_SELECT)
        except pyodbc.ProgrammingError as exc:
            err = str(exc).lower()
            if "vendedor_nome" in err and "ultima_venda" in err:
                logging.warning("View sem colunas vendedor_nome/ultima_venda; usando fallback nulo")
                cur.execute(SQL_SELECT_FALLBACK_NO_SALES_NO_VENDOR)
            elif "vendedor_nome" in err:
                logging.warning("View sem coluna vendedor_nome; usando fallback com valor nulo")
                cur.execute(SQL_SELECT_FALLBACK_NO_STATUS_VENDOR)
            elif "ultima_venda" in err:
                logging.warning("View sem colunas de última venda; usando fallback com valores nulos")
                cur.execute(SQL_SELECT_FALLBACK_NO_SALES)
            else:
                raise
        columns = [col[0] for col in cur.description]
        rows = cur.fetchall()

        clientes = []
        for row in rows:
            item = dict(zip(columns, row))
            # A view foi ajustada para entregar o nome do vendedor em vendedor_nome.
            # Garantimos que sempre exista essa chave, mesmo que o nome venha em outra coluna.
            if "vendedor_nome" not in item:
                item["vendedor_nome"] = item.get("vendedor") or None
            elif not item["vendedor_nome"] and "vendedor" in item:
                item["vendedor_nome"] = item.get("vendedor") or None

            # Normaliza campos de data/valor para JSON
            if "ultima_venda_data" in item and item["ultima_venda_data"] is not None:
                try:
                    item["ultima_venda_data"] = item["ultima_venda_data"].isoformat()
                except Exception:
                    item["ultima_venda_data"] = str(item["ultima_venda_data"])
            if "ultima_venda_valor" in item and item["ultima_venda_valor"] is not None:
                try:
                    item["ultima_venda_valor"] = float(item["ultima_venda_valor"])
                except Exception:
                    pass

            clientes.append(item)

        return clientes

    except Exception as e:
        logging.error(f"Erro ao buscar clientes no SQL Server: {e}")
        raise

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def send_batch(batch):
    """Envia lote para API"""
    token = _obter_token()
    resp = requests.post(
        API_URL,
        json=batch,
        headers={"Authorization": f"Bearer {token}"},
        timeout=API_TIMEOUT
    )

    if resp.status_code != 200:
        raise Exception(
            f"Erro API {resp.status_code} - {resp.text}"
        )

    return resp.json()


def chunk_list(data, size):
    """Divide lista em lotes"""
    for i in range(0, len(data), size):
        yield data[i:i + size]


def _obter_token():
    resp = requests.post(
        API_LOGIN_URL,
        json={"username": API_USERNAME, "password": API_PASSWORD},
        timeout=API_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("token", {}).get("access_token")
    if not token:
        raise RuntimeError("Token não retornado pela API")
    return token


# ==================================================
# MAIN
# ==================================================

def main():
    logging.info("=== INÍCIO SYNC CLIENTES ===")

    clientes = fetch_clientes()
    total = len(clientes)

    if total == 0:
        logging.warning("Nenhum cliente encontrado na view vw_clientes_com_vendedor")
        return

    logging.info(f"Total de clientes encontrados: {total}")

    if BATCH_SIZE <= 0:
        total_lotes = 1
        lotes = [clientes]
    else:
        total_lotes = ceil(total / BATCH_SIZE)
        lotes = chunk_list(clientes, BATCH_SIZE)

    enviados = 0

    for idx, batch in enumerate(lotes, start=1):
        try:
            result = send_batch(batch)
            enviados += len(batch)

            logging.info(
                f"Lote {idx}/{total_lotes} OK | "
                f"Registros: {len(batch)} | "
                f"Resposta API: {result}"
            )

        except Exception as e:
            logging.error(
                f"Lote {idx}/{total_lotes} ERRO | {e}"
            )

    logging.info(
        f"=== FIM SYNC CLIENTES | Enviados {enviados}/{total} ==="
    )


if __name__ == "__main__":
    main()
