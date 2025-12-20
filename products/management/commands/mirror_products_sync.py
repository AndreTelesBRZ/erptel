import os
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


class Command(BaseCommand):
    help = (
        'Espelha a view SQL Server dbo.vw_produtos_sync_preco_estoque '
        'para a tabela Postgres erp_produtos_sync (banco erptel).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--chunk-size',
            type=int,
            default=1000,
            help='Quantidade de linhas processadas por lote (default: 1000).',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limita a quantidade de registros lidos da view (para teste).',
        )
        parser.add_argument(
            '--update',
            action='store_true',
            help='Atualiza registros existentes (sempre verdadeiro neste comando).',
        )

    def _get_mssql_conn(self):
        try:
            import pyodbc
        except ImportError:
            raise CommandError('pyodbc não instalado. Adicione ao requirements e instale no ambiente.')

        dsn = os.getenv('MSSQL_DSN')
        driver = os.getenv('MSSQL_DRIVER', 'ODBC Driver 17 for SQL Server')
        host = os.getenv('MSSQL_HOST', '127.0.0.1')
        port = os.getenv('MSSQL_PORT', '1433')
        db = os.getenv('MSSQL_DB', 'SysacME')
        user = os.getenv('MSSQL_USER')
        password = os.getenv('MSSQL_PASSWORD')
        encrypt = os.getenv('MSSQL_ENCRYPT')
        trust_cert = os.getenv('MSSQL_TRUST_CERT')
        login_timeout = os.getenv('MSSQL_LOGIN_TIMEOUT')

        if dsn:
            parts = [f"DSN={dsn}", f"DATABASE={db}"]
        else:
            parts = [f"DRIVER={{{driver}}}", f"SERVER={host},{port}", f"DATABASE={db}"]

        if user:
            parts.extend([f"UID={user}", f"PWD={password or ''}"])
        else:
            parts.append("Trusted_Connection=yes")

        for key, value in (
            ('Encrypt', encrypt),
            ('TrustServerCertificate', trust_cert),
            ('LoginTimeout', login_timeout),
        ):
            if value:
                parts.append(f"{key}={value}")

        conn_str = ";".join(parts)
        try:
            return pyodbc.connect(conn_str)
        except Exception as exc:
            raise CommandError(f'Falha ao conectar no SQL Server: {exc}')

    @staticmethod
    def _decimal_or_none(value):
        if value in (None, '',):
            return None
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except Exception:
            return None

    def handle(self, *args, **options):
        chunk_size = options['chunk_size'] or 1000
        limit = options.get('limit')

        mssql_conn = self._get_mssql_conn()
        src_cursor = mssql_conn.cursor()

        def build_sql(include_refplu: bool, include_rowhash: bool) -> str:
            select_prefix = "SELECT "
            if limit:
                select_prefix += f"TOP ({int(limit)}) "
            cols = [
                "Codigo",
                "DescricaoCompleta",
                "Referencia",
                "Secao",
                "Grupo",
                "Subgrupo",
                "Unidade",
                "EAN",
                "PLU",
                "PrecoNormal",
                "PrecoPromocao1",
                "PrecoPromocao2",
                "Custo",
                "EstoqueDisponivel",
                "Loja",
            ]
            if include_refplu:
                cols.append("REFPLU")
            if include_rowhash:
                cols.append("RowHash")
            col_sql = ", ".join(cols)
            return f"{select_prefix}{col_sql} FROM dbo.vw_produtos_sync_preco_estoque"

        has_refplu = True
        has_rowhash = True
        sql = build_sql(include_refplu=True, include_rowhash=True)
        try:
            src_cursor.execute(sql)
        except Exception as exc:
            err = str(exc).lower()
            if 'refplu' in err or 'ref plu' in err:
                has_refplu = False
            if 'rowhash' in err:
                has_rowhash = False
            if not has_refplu or not has_rowhash:
                sql = build_sql(include_refplu=has_refplu, include_rowhash=has_rowhash)
                try:
                    src_cursor.execute(sql)
                except Exception as exc2:
                    mssql_conn.close()
                    raise CommandError(f'Falha ao consultar a view no SQL Server: {exc2}')
            else:
                mssql_conn.close()
                raise CommandError(f'Falha ao consultar a view no SQL Server: {exc}')

        insert_sql = """
            INSERT INTO erp_produtos_sync (
                codigo, descricao_completa, referencia, secao, grupo, subgrupo, unidade,
                ean, plu, preco_normal, preco_promocao1, preco_promocao2, custo,
                estoque_disponivel, loja, refplu, row_hash, updated_at
            ) VALUES (
                %(codigo)s, %(descricao_completa)s, %(referencia)s, %(secao)s, %(grupo)s, %(subgrupo)s, %(unidade)s,
                %(ean)s, %(plu)s, %(preco_normal)s, %(preco_promocao1)s, %(preco_promocao2)s, %(custo)s,
                %(estoque_disponivel)s, %(loja)s, %(refplu)s, %(row_hash)s, now()
            )
            ON CONFLICT (codigo, loja) DO UPDATE SET
                descricao_completa = EXCLUDED.descricao_completa,
                referencia = EXCLUDED.referencia,
                secao = EXCLUDED.secao,
                grupo = EXCLUDED.grupo,
                subgrupo = EXCLUDED.subgrupo,
                unidade = EXCLUDED.unidade,
                ean = EXCLUDED.ean,
                plu = EXCLUDED.plu,
                preco_normal = EXCLUDED.preco_normal,
                preco_promocao1 = EXCLUDED.preco_promocao1,
                preco_promocao2 = EXCLUDED.preco_promocao2,
                custo = EXCLUDED.custo,
                estoque_disponivel = EXCLUDED.estoque_disponivel,
                refplu = EXCLUDED.refplu,
                row_hash = EXCLUDED.row_hash,
                updated_at = now()
            WHERE erp_produtos_sync.row_hash IS DISTINCT FROM EXCLUDED.row_hash
        """

        processed = 0
        try:
            with transaction.atomic():
                with connection.cursor() as pg_cursor:
                    while True:
                        batch = src_cursor.fetchmany(chunk_size)
                        if not batch:
                            break
                        payload = []
                        for r in batch:
                            codigo = (r.Codigo or '').strip()
                            loja = (r.Loja or '').strip()
                            if not codigo or not loja:
                                continue
                            preco_normal = self._decimal_or_none(r.PrecoNormal)
                            preco_promocao1 = self._decimal_or_none(r.PrecoPromocao1)
                            preco_promocao2 = self._decimal_or_none(r.PrecoPromocao2)
                            custo = self._decimal_or_none(getattr(r, 'Custo', None))
                            if preco_normal is None:
                                preco_normal = next(
                                    (p for p in (preco_promocao1, preco_promocao2) if p is not None),
                                    None
                                )
                            payload.append({
                                'codigo': codigo,
                                'descricao_completa': (r.DescricaoCompleta or '').strip(),
                                'referencia': (r.Referencia or '').strip() or None,
                                'secao': (r.Secao or '').strip() or None,
                                'grupo': (r.Grupo or '').strip() or None,
                                'subgrupo': (r.Subgrupo or '').strip() or None,
                                'unidade': (r.Unidade or '').strip() or None,
                                'ean': (r.EAN or '').strip() or None,
                                'plu': (r.PLU or '').strip() or None,
                                'preco_normal': preco_normal,
                                'preco_promocao1': preco_promocao1,
                                'preco_promocao2': preco_promocao2,
                                'custo': custo,
                                'estoque_disponivel': self._decimal_or_none(r.EstoqueDisponivel),
                                'loja': loja,
                                'refplu': (getattr(r, 'REFPLU', None) or '').strip() or None if has_refplu else None,
                                'row_hash': (getattr(r, 'RowHash', None) or '').strip() or None if has_rowhash else None,
                            })
                        for row in payload:
                            pg_cursor.execute(insert_sql, row)
                        processed += len(batch)
        finally:
            mssql_conn.close()
        self.stdout.write(self.style.SUCCESS(f'Processados {processed} registros (upsert em erp_produtos_sync).'))
