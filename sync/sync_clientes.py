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
API_TENANT_DOMAIN = os.getenv("API_TENANT_DOMAIN", "")
API_TENANT_HEADER = os.getenv("API_TENANT_HEADER", "X-Forwarded-Host")

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

VIEW_NAME = "dbo.vw_clientes_com_vendedor_geral"


def _fetch_view_columns(cur):
    cur.execute(f"SELECT TOP 0 * FROM {VIEW_NAME}")
    return {col[0].lower(): col[0] for col in cur.description}


def _column_expr(columns, candidates, alias):
    for candidate in candidates:
        col = columns.get(candidate.lower())
        if col:
            return f"{col} AS {alias}"
    return f"NULL AS {alias}"


def _build_select(columns):
    vendedor_nome = _column_expr(columns, ["vendedor_nome", "vendedor"], "vendedor_nome")
    ultima_venda_data = _column_expr(
        columns,
        ["data_ultima_venda", "ultima_venda_data"],
        "ultima_venda_data",
    )
    ultima_venda_valor = _column_expr(
        columns,
        ["valor_ultima_venda", "ultima_venda_valor"],
        "ultima_venda_valor",
    )
    limite_credito = _column_expr(
        columns,
        [
            "limite_credito",
            "limite_credito_cliente",
            "limite_credito_total",
            "limite_de_credito",
            "credito_limite",
        ],
        "limite_credito",
    )
    row_hash = _column_expr(columns, ["row_hash", "rowhash", "row_hash_cliente"], "row_hash")
    return f"""
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
    {limite_credito},
    {row_hash},
    vendedor_codigo,
    {vendedor_nome},
    {ultima_venda_data},
    {ultima_venda_valor}
FROM {VIEW_NAME}
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

        columns_map = _fetch_view_columns(cur)
        sql = _build_select(columns_map)
        if "limite_credito" not in columns_map:
            logging.warning("View sem coluna limite_credito; usando valor nulo")
        if "row_hash" not in columns_map and "rowhash" not in columns_map:
            logging.warning("View sem coluna row_hash/rowhash; usando valor nulo")
        if "vendedor_nome" not in columns_map and "vendedor" not in columns_map:
            logging.warning("View sem coluna vendedor_nome; usando valor nulo")
        if "data_ultima_venda" not in columns_map and "ultima_venda_data" not in columns_map:
            logging.warning("View sem coluna data_ultima_venda; usando valor nulo")
        if "valor_ultima_venda" not in columns_map and "ultima_venda_valor" not in columns_map:
            logging.warning("View sem coluna valor_ultima_venda; usando valor nulo")
        cur.execute(sql)
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
            if "limite_credito" in item and item["limite_credito"] is not None:
                try:
                    item["limite_credito"] = float(item["limite_credito"])
                except Exception:
                    pass
            if "row_hash" in item and item["row_hash"] is not None:
                item["row_hash"] = str(item["row_hash"])

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


def _build_headers(token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if API_TENANT_DOMAIN:
        headers[API_TENANT_HEADER] = API_TENANT_DOMAIN
    return headers


def send_batch(batch):
    """Envia lote para API"""
    token = _obter_token()
    resp = requests.post(
        API_URL,
        json=batch,
        headers=_build_headers(token),
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
        headers=_build_headers(),
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
        logging.warning("Nenhum cliente encontrado na view vw_clientes_com_vendedor_geral")
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
