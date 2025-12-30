import os
import logging
import requests
import pyodbc
from math import ceil

API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:9000")
API_URL = os.getenv("API_PRODUTOS_URL", f"{API_BASE}/api/products/sync")
API_LOGIN_URL = os.getenv("API_LOGIN_URL", f"{API_BASE}/auth/login")
API_USERNAME = os.getenv("API_USERNAME", "apiadmin")
API_PASSWORD = os.getenv("API_PASSWORD", "TroqueEstaSenha!")
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "60"))
API_TENANT_DOMAIN = os.getenv("API_TENANT_DOMAIN", "")
API_TENANT_HEADER = os.getenv("API_TENANT_HEADER", "X-Forwarded-Host")
BATCH_SIZE = int(os.getenv("PRODUTOS_BATCH_SIZE", "500"))
MSSQL_PRODUTOS_VIEWS = os.getenv(
    "MSSQL_PRODUTOS_VIEWS",
    "dbo.vw_produtos_sync_preco_estoque,dbo.vw_produtos_sync_preco_estoque_000003",
)
LOG_FILE = "/home/ubuntu/apps/Django/sync/sync.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | PRODUTOS | %(levelname)s | %(message)s",
)

conn_str = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=10.0.0.60,1433;"
    "DATABASE=SysacME;"
    "UID=sync_erptel;"
    "PWD=SenhaForte@2025;"
    "Encrypt=no;"
    "TrustServerCertificate=yes;"
)


def _build_headers(token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if API_TENANT_DOMAIN:
        headers[API_TENANT_HEADER] = API_TENANT_DOMAIN
    return headers


def conectar_mssql():
    return pyodbc.connect(conn_str)


def obter_produtos():
    conn = conectar_mssql()
    cursor = conn.cursor()
    views = [v.strip() for v in MSSQL_PRODUTOS_VIEWS.split(",") if v.strip()]
    produtos = []
    for view_name in views:
        query = f"""
            SELECT 
                Codigo,
                DescricaoCompleta,
                Referencia,
                Secao,
                Grupo,
                Subgrupo,
                Unidade,
                EAN,
                PLU,
                PrecoNormal,
                PrecoPromocao1,
                PrecoPromocao2,
                Custo,
                EstoqueDisponivel,
                Loja,
                RowHash
            FROM {view_name}
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        if not rows:
            logging.warning("Nenhum produto encontrado na view %s", view_name)
            continue
        for r in rows:
            produtos.append({
                "codigo": str(r.Codigo or "").zfill(8),
                "descricao_completa": (r.DescricaoCompleta or "").strip(),
                "referencia": (getattr(r, "Referencia", None) or "").strip(),
                "secao": (getattr(r, "Secao", None) or "").strip(),
                "grupo": (getattr(r, "Grupo", None) or "").strip(),
                "subgrupo": (getattr(r, "Subgrupo", None) or "").strip(),
                "unidade": (r.Unidade or "").strip(),
                "ean": (r.EAN or "").strip(),
                "plu": str(r.PLU or "").zfill(6),
                "preco_normal": float(r.PrecoNormal or 0),
                "preco_promocao1": float(r.PrecoPromocao1 or 0),
                "preco_promocao2": float(r.PrecoPromocao2 or 0),
                "estoque_disponivel": float(r.EstoqueDisponivel or 0),
                "custo": float(r.Custo or 0),
                "loja": str(getattr(r, "Loja", None) or "000001").strip(),
                "row_hash": r.RowHash,
            })

    conn.close()
    return produtos


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


def enviar_api(produtos):
    try:
        token = _obter_token()
        response = requests.post(
            API_URL,
            json=produtos,
            headers=_build_headers(token),
            timeout=API_TIMEOUT,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Erro API {response.status_code} - {response.text}")
        return response.json()

    except Exception as e:
        raise RuntimeError(f"Erro ao enviar lote: {e}") from e

    return {}


def run():
    logging.info("=== INICIO SYNC PRODUTOS ===")
    produtos = obter_produtos()
    total = len(produtos)
    if total == 0:
        logging.warning("Nenhum produto encontrado nas views %s", MSSQL_PRODUTOS_VIEWS)
        return

    logging.info("Total de produtos encontrados: %s", total)
    if BATCH_SIZE <= 0:
        total_lotes = 1
        lotes = [produtos]
    else:
        total_lotes = ceil(total / BATCH_SIZE)
        lotes = (produtos[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE))

    enviados = 0
    for idx, batch in enumerate(lotes, start=1):
        try:
            result = enviar_api(batch)
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

    logging.info("=== FIM SYNC PRODUTOS | Enviados %s/%s ===", enviados, total)


if __name__ == "__main__":
    run()
