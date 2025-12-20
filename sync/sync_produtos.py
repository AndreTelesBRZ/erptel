import os
import requests
import pyodbc
from datetime import datetime

API_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:9000")
API_URL = os.getenv("API_PRODUTOS_URL", f"{API_BASE}/api/products/sync")
API_LOGIN_URL = os.getenv("API_LOGIN_URL", f"{API_BASE}/auth/login")
API_USERNAME = os.getenv("API_USERNAME", "apiadmin")
API_PASSWORD = os.getenv("API_PASSWORD", "TroqueEstaSenha!")
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "60"))

conn_str = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=10.0.0.60,1433;"
    "DATABASE=SysacME;"
    "UID=sync_erptel;"
    "PWD=SenhaForte@2025;"
    "Encrypt=no;"
    "TrustServerCertificate=yes;"
)


def conectar_mssql():
    return pyodbc.connect(conn_str)


def obter_produtos():
    conn = conectar_mssql()
    cursor = conn.cursor()

    query = """
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
        FROM vw_produtos_sync_preco_estoque
    """

    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()

    produtos = []
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

    return produtos


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


def enviar_api(produtos):
    print(f"\n===== INICIANDO SINCRONIZAÇÃO =====")
    print(f"{datetime.now()} Enviando {len(produtos)} produtos...")

    try:
        token = _obter_token()
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.post(API_URL, json=produtos, headers=headers, timeout=API_TIMEOUT)
        print("Status:", response.status_code)
        print("Resposta:", response.text)

    except Exception as e:
        print("Erro ao enviar:", e)

    print("===== FINALIZADO =====\n")


def run():
    produtos = obter_produtos()
    enviar_api(produtos)


if __name__ == "__main__":
    run()
