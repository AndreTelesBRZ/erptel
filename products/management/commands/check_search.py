from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Verifica Postgres, extensão pg_trgm e índices de trigram. Tenta criar a extensão se faltando."

    def handle(self, *args, **options):
        vendor = connection.vendor
        self.stdout.write(self.style.NOTICE(f"DB vendor: {vendor}"))
        if vendor != 'postgresql':
            self.stdout.write("Banco não é PostgreSQL; nada para verificar.")
            return

        with connection.cursor() as cur:
            cur.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_trgm')")
            (installed,) = cur.fetchone()
        self.stdout.write(f"pg_trgm instalado: {installed}")
        if not installed:
            self.stdout.write("Criando extensão pg_trgm (se permitido)...")
            with connection.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
            self.stdout.write("Extensão garantida.")

        # Listar índices trgm relevantes
        idx_tables = [
            ('products_product', 'products % trgm'),
            ('clients_client', 'clients % trgm'),
        ]
        for table, label in idx_tables:
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT indexname FROM pg_indexes WHERE tablename=%s AND indexname ILIKE %s",
                    [table, '%trgm%']
                )
                rows = [r[0] for r in cur.fetchall()]
            self.stdout.write(f"{label}: {rows or 'nenhum índice encontrado'}")

        self.stdout.write(self.style.SUCCESS("Verificação concluída."))

