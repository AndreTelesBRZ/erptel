import os
import logging
from math import ceil
from decimal import Decimal

import pyodbc
import requests

# ==================================================
# CONFIGURACOES
# ==================================================
SQLSERVER_CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=10.0.0.60,1433;"
    "DATABASE=SysacME;"
    "UID=sync_erptel;"
    "PWD=SenhaForte@2025;"
    "Encrypt=no;"
    "TrustServerCertificate=yes;"
)

API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:9000")
API_URL = os.getenv("API_PLANOS_URL", f"{API_BASE}/api/planos-pagamento-clientes/sync")
API_LOGIN_URL = os.getenv("API_LOGIN_URL", f"{API_BASE}/auth/login")
API_USERNAME = os.getenv("API_USERNAME", "apiadmin")
API_PASSWORD = os.getenv("API_PASSWORD", "TroqueEstaSenha!")
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "60"))
API_TENANT_DOMAIN = os.getenv("API_TENANT_DOMAIN", "")
API_TENANT_HEADER = os.getenv("API_TENANT_HEADER", "X-Forwarded-Host")
BATCH_SIZE = int(os.getenv("PLANOS_BATCH_SIZE", "500"))

LOG_FILE = "/home/ubuntu/apps/Django/sync/sync.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | PLANOS | %(levelname)s | %(message)s",
)

SQL_SELECT = """
SELECT
    CLICOD,
    PLACOD,
    PLADES,
    PLAENT,
    PLAINTPRI,
    PLAINTPAR,
    PLANUMPAR,
    PLAVLRMIN,
    PLAVLRACR
FROM dbo.V_PLANO_PAGAMENTO_CLIENTE
"""


def _build_headers(token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if API_TENANT_DOMAIN:
        headers[API_TENANT_HEADER] = API_TENANT_DOMAIN
    return headers


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
        raise RuntimeError("Token nao retornado pela API")
    return token


def fetch_planos():
    conn = None
    cur = None
    try:
        conn = pyodbc.connect(SQLSERVER_CONN_STR, timeout=10)
        cur = conn.cursor()
        cur.execute(SQL_SELECT)
        columns = [col[0] for col in cur.description]
        rows = cur.fetchall()
        planos = [_normalize_row(dict(zip(columns, row))) for row in rows]
        return planos
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _normalize_row(row: dict) -> dict:
    normalized = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            normalized[key] = str(value)
        else:
            normalized[key] = value
    return normalized


def send_batch(batch):
    token = _obter_token()
    resp = requests.post(
        API_URL,
        json=batch,
        headers=_build_headers(token),
        timeout=API_TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Erro API {resp.status_code} - {resp.text}")
    return resp.json()


def chunk_list(data, size):
    for i in range(0, len(data), size):
        yield data[i:i + size]


def main():
    logging.info("=== INICIO SYNC PLANOS PAGAMENTO ===")
    planos = fetch_planos()
    total = len(planos)
    if total == 0:
        logging.warning("Nenhum plano encontrado na view V_PLANO_PAGAMENTO_CLIENTE")
        return

    logging.info("Total de planos encontrados: %s", total)
    if BATCH_SIZE <= 0:
        total_lotes = 1
        lotes = [planos]
    else:
        total_lotes = ceil(total / BATCH_SIZE)
        lotes = chunk_list(planos, BATCH_SIZE)

    enviados = 0
    for idx, batch in enumerate(lotes, start=1):
        try:
            result = send_batch(batch)
            enviados += len(batch)
            logging.info(
                "Lote %s/%s OK | Registros: %s | Resposta API: %s",
                idx,
                total_lotes,
                len(batch),
                result,
            )
        except Exception as exc:
            logging.error("Lote %s/%s ERRO | %s", idx, total_lotes, exc)

    logging.info("=== FIM SYNC PLANOS PAGAMENTO | Enviados %s/%s ===", enviados, total)


if __name__ == "__main__":
    main()
