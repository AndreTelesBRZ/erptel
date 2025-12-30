import hashlib
import logging
import os
from datetime import date
from math import ceil
from typing import Any

import pyodbc
import psycopg2
from psycopg2.extras import execute_values

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

if load_dotenv:
    load_dotenv("/home/ubuntu/apps/Django/.env")


# ==================================================
# CONFIGURACOES
# ==================================================
SQLSERVER_CONN_STR = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={os.getenv('SQLSERVER_HOST', '10.0.0.60')},{os.getenv('SQLSERVER_PORT', '1433')};"
    f"DATABASE={os.getenv('SQLSERVER_DB', 'SysacME')};"
    f"UID={os.getenv('SQLSERVER_USER', 'sync_erptel')};"
    f"PWD={os.getenv('SQLSERVER_PASSWORD', 'SenhaForte@2025')};"
    f"Encrypt={os.getenv('SQLSERVER_ENCRYPT', 'yes')};"
    f"TrustServerCertificate={os.getenv('SQLSERVER_TRUST_CERT', 'yes')};"
)

PG_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_DB = os.getenv("POSTGRES_DB", "erptel")
PG_USER = os.getenv("POSTGRES_USER", "postgres")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "minhasenha")

BATCH_SIZE = int(os.getenv("INADIMPLENCIA_BATCH_SIZE", "500"))
CLEAR_ON_EMPTY = os.getenv("INADIMPLENCIA_CLEAR_ON_EMPTY", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

LOG_FILE = "/home/ubuntu/apps/Django/sync/sync.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | INADIMPLENCIA | %(levelname)s | %(message)s",
)


SQL_SELECT = """
SELECT
    cod_loja,
    cod_vendedor,
    num_titulo,
    cod_cliente,
    razao_social,
    nome_fantasia,
    cpf_cnpj,
    tipo_doc,
    documento_tipo,
    cidade,
    vencimento,
    vencimento_real,
    valor_devedor
FROM dbo.vw_inadimplencia
"""


def _hash_row(row: dict[str, Any]) -> str:
    vencimento_base = row.get("vencimento_real") or row.get("vencimento")
    parts = [
        row.get("cod_loja"),
        row.get("cod_vendedor"),
        row.get("num_titulo"),
        row.get("cod_cliente"),
        row.get("razao_social"),
        row.get("nome_fantasia"),
        row.get("cpf_cnpj"),
        row.get("tipo_doc"),
        row.get("documento_tipo"),
        row.get("cidade"),
        vencimento_base,
        row.get("valor_devedor"),
    ]
    normalized = []
    for value in parts:
        if value is None:
            normalized.append("")
        elif isinstance(value, (date,)):
            normalized.append(value.isoformat())
        else:
            normalized.append(str(value).strip())
    raw = "|".join(normalized)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def fetch_inadimplencia() -> list[dict[str, Any]]:
    conn = None
    cur = None
    try:
        conn = pyodbc.connect(SQLSERVER_CONN_STR, timeout=10)
        cur = conn.cursor()
        cur.execute(SQL_SELECT)
        columns = [col[0] for col in cur.description]
        rows = cur.fetchall()
        results = []
        for row in rows:
            item = dict(zip(columns, row))
            item["hash_registro"] = _hash_row(item)
            results.append(item)
        return results
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _pg_connect():
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
    )


def _existing_hashes(cur, keys: list[tuple[str, str]]) -> dict[tuple[str, str], str | None]:
    if not keys:
        return {}
    normalized_keys = []
    for cod_loja, num_titulo in keys:
        cod_loja_str = str(cod_loja).strip() if cod_loja is not None else ""
        num_titulo_str = str(num_titulo).strip() if num_titulo is not None else ""
        normalized_keys.append((cod_loja_str, num_titulo_str))
    sql = """
        SELECT e.cod_loja, e.num_titulo, e.hash_registro
        FROM erp_inadimplencia e
        JOIN (VALUES %s) AS v(cod_loja, num_titulo)
          ON e.cod_loja = v.cod_loja AND e.num_titulo = v.num_titulo
    """
    result = {}
    execute_values(cur, sql, normalized_keys)
    for cod_loja, num_titulo, hash_registro in cur.fetchall():
        result[(cod_loja, num_titulo)] = hash_registro
    return result


def _chunk_list(data, size):
    for i in range(0, len(data), size):
        yield data[i : i + size]


def upsert_batch(cur, rows: list[dict[str, Any]]) -> tuple[int, int]:
    keys = [(r.get("cod_loja"), r.get("num_titulo")) for r in rows]
    existing = _existing_hashes(cur, keys)
    inserted = 0
    updated = 0
    for row in rows:
        key = (row.get("cod_loja"), row.get("num_titulo"))
        prev_hash = existing.get(key)
        if prev_hash is None:
            inserted += 1
        elif prev_hash != row.get("hash_registro"):
            updated += 1

    sql = """
        INSERT INTO erp_inadimplencia (
            cod_loja,
            cod_vendedor,
            num_titulo,
            cod_cliente,
            razao_social,
            nome_fantasia,
            cpf_cnpj,
            tipo_doc,
            documento_tipo,
            cidade,
            vencimento,
            vencimento_real,
            valor_devedor,
            hash_registro
        ) VALUES %s
        ON CONFLICT (cod_loja, num_titulo)
        DO UPDATE SET
            cod_vendedor = EXCLUDED.cod_vendedor,
            cod_cliente = EXCLUDED.cod_cliente,
            razao_social = EXCLUDED.razao_social,
            nome_fantasia = EXCLUDED.nome_fantasia,
            cpf_cnpj = EXCLUDED.cpf_cnpj,
            tipo_doc = EXCLUDED.tipo_doc,
            documento_tipo = EXCLUDED.documento_tipo,
            cidade = EXCLUDED.cidade,
            vencimento = EXCLUDED.vencimento,
            vencimento_real = EXCLUDED.vencimento_real,
            valor_devedor = EXCLUDED.valor_devedor,
            hash_registro = EXCLUDED.hash_registro,
            last_sync = NOW()
        WHERE erp_inadimplencia.hash_registro IS DISTINCT FROM EXCLUDED.hash_registro;
    """

    values = [
        (
            r.get("cod_loja"),
            r.get("cod_vendedor"),
            r.get("num_titulo"),
            r.get("cod_cliente"),
            r.get("razao_social"),
            r.get("nome_fantasia"),
            r.get("cpf_cnpj"),
            r.get("tipo_doc"),
            r.get("documento_tipo"),
            r.get("cidade"),
            r.get("vencimento"),
            r.get("vencimento_real"),
            r.get("valor_devedor"),
            r.get("hash_registro"),
        )
        for r in rows
    ]
    execute_values(cur, sql, values, page_size=len(values))
    return inserted, updated


def main():
    logging.info("=== INICIO SYNC INADIMPLENCIA ===")
    rows = fetch_inadimplencia()
    total = len(rows)
    if total == 0:
        logging.warning("Nenhum registro encontrado na view v_inadimplencia")
        if CLEAR_ON_EMPTY:
            conn = None
            cur = None
            try:
                conn = _pg_connect()
                cur = conn.cursor()
                cur.execute("DELETE FROM erp_inadimplencia;")
                conn.commit()
                logging.info("Tabela erp_inadimplencia limpa (view vazia).")
            except Exception as exc:
                if conn:
                    conn.rollback()
                logging.exception("Erro ao limpar erp_inadimplencia: %s", exc)
                raise
            finally:
                if cur:
                    cur.close()
                if conn:
                    conn.close()
        return

    logging.info("Total de registros encontrados: %s", total)
    if BATCH_SIZE <= 0:
        total_lotes = 1
        lotes = [rows]
    else:
        total_lotes = ceil(total / BATCH_SIZE)
        lotes = _chunk_list(rows, BATCH_SIZE)

    conn = None
    cur = None
    try:
        conn = _pg_connect()
        cur = conn.cursor()
        inserted_total = 0
        updated_total = 0
        for idx, batch in enumerate(lotes, start=1):
            inserted, updated = upsert_batch(cur, batch)
            conn.commit()
            inserted_total += inserted
            updated_total += updated
            logging.info(
                "Lote %s/%s OK | Registros: %s | Inseridos: %s | Atualizados: %s",
                idx,
                total_lotes,
                len(batch),
                inserted,
                updated,
            )
        logging.info(
            "=== FIM SYNC INADIMPLENCIA | Inseridos %s | Atualizados %s | Total %s ===",
            inserted_total,
            updated_total,
            total,
        )
    except Exception as exc:
        if conn:
            conn.rollback()
        logging.exception("Erro ao sincronizar inadimplencia: %s", exc)
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
