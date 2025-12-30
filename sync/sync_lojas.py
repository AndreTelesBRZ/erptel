import os
import logging
from math import ceil

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
API_URL = os.getenv("API_LOJAS_URL", f"{API_BASE}/api/lojas/sync")
API_LOGIN_URL = os.getenv("API_LOGIN_URL", f"{API_BASE}/auth/login")
API_USERNAME = os.getenv("API_USERNAME", "apiadmin")
API_PASSWORD = os.getenv("API_PASSWORD", "TroqueEstaSenha!")
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "60"))
API_TENANT_DOMAIN = os.getenv("API_TENANT_DOMAIN", "")
API_TENANT_HEADER = os.getenv("API_TENANT_HEADER", "X-Forwarded-Host")
BATCH_SIZE = int(os.getenv("LOJAS_BATCH_SIZE", "500"))

LOG_FILE = "/home/ubuntu/apps/Django/sync/sync.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | LOJAS | %(levelname)s | %(message)s",
)

SQL_SELECT = """
SELECT
    LOJCOD,
    AGEDES,
    AGEFAN,
    AGECGCCPF,
    AGECGFRG,
    AGEPFPJ,
    AGETEL1,
    AGETEL2,
    AGEEND,
    AGEBAI,
    AGENUM,
    AGECPL,
    AGECEP,
    AGECORELE,
    AGECID,
    AGEEST
FROM dbo.V_LOJA
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


def fetch_lojas():
    conn = None
    cur = None
    try:
        conn = pyodbc.connect(SQLSERVER_CONN_STR, timeout=10)
        cur = conn.cursor()
        cur.execute(SQL_SELECT)
        columns = [col[0] for col in cur.description]
        rows = cur.fetchall()
        lojas = [dict(zip(columns, row)) for row in rows]
        return lojas
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


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
    logging.info("=== INICIO SYNC LOJAS ===")
    lojas = fetch_lojas()
    total = len(lojas)
    if total == 0:
        logging.warning("Nenhuma loja encontrada na view V_LOJA")
        return

    logging.info("Total de lojas encontradas: %s", total)
    if BATCH_SIZE <= 0:
        total_lotes = 1
        lotes = [lojas]
    else:
        total_lotes = ceil(total / BATCH_SIZE)
        lotes = chunk_list(lojas, BATCH_SIZE)

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

    logging.info("=== FIM SYNC LOJAS | Enviados %s/%s ===", enviados, total)


if __name__ == "__main__":
    main()
