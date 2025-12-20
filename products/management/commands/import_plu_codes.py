import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from products.models import Product

DEFAULT_PLU_PATH = Path("/home/ubuntu/apps/Django/.venv/plu.csv")


class Command(BaseCommand):
    help = "Atualiza o campo PLU dos produtos a partir do arquivo plu.csv fornecido."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(DEFAULT_PLU_PATH),
            help=f"Caminho do arquivo CSV de PLUs (default: {DEFAULT_PLU_PATH}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Executa em modo simulação, sem alterar o banco.",
        )

    def handle(self, *args, **options):
        file_path = Path(options["file"]).expanduser()
        if not file_path.exists():
            raise CommandError(f"Arquivo não encontrado: {file_path}")

        updated = 0
        unchanged = 0
        missing = []

        with file_path.open("r", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            if reader.fieldnames is None:
                raise CommandError("Arquivo CSV sem cabeçalho. Esperado colunas CODIGO e PLU.")
            norm_fields = [field.strip().lower() for field in reader.fieldnames]
            try:
                idx_code = norm_fields.index("codigo")
                idx_plu = norm_fields.index("plu")
            except ValueError:
                raise CommandError("Cabeçalho deve conter as colunas 'CODIGO' e 'PLU'.")
            code_field = reader.fieldnames[idx_code]
            plu_field = reader.fieldnames[idx_plu]

            rows = list(reader)

        if not rows:
            self.stdout.write(self.style.WARNING("Nenhuma linha encontrada no arquivo."))
            return

        def normalize(value: str | None) -> str | None:
            if value is None:
                return None
            cleaned = str(value).strip()
            return cleaned or None

        def normalize_plu(value: str | None) -> str | None:
            cleaned = normalize(value)
            if not cleaned:
                return None
            digits = "".join(ch for ch in cleaned if ch.isdigit())
            if digits:
                stripped = digits.lstrip("0")
                return stripped or "0"
            return cleaned

        with transaction.atomic():
            for row in rows:
                raw_code = normalize(row.get(code_field))
                raw_plu = normalize_plu(row.get(plu_field))
                if not raw_code or not raw_plu:
                    continue

                candidates = {raw_code, raw_code.lstrip("0")}
                candidates = {c for c in candidates if c}

                product = Product.objects.filter(code__in=candidates).order_by("id").first()
                if not product:
                    # tenta buscar em referência ou códigos extra
                    query = Q()
                    for candidate in candidates:
                        query |= Q(reference__iregex=rf"(^|;)\s*{candidate}\s*(;|$)")
                        query |= Q(supplier_code__iexact=candidate)
                    product = Product.objects.filter(query).order_by("id").first()

                if not product:
                    missing.append(raw_code)
                    continue

                if product.plu_code == raw_plu:
                    unchanged += 1
                    continue

                if options["dry_run"]:
                    updated += 1
                    continue

                product.plu_code = raw_plu
                product.save(update_fields=["plu_code"])
                updated += 1

        summary = f"Processados: {len(rows)} | Atualizados: {updated} | Inalterados: {unchanged} | Não encontrados: {len(missing)}"
        if options["dry_run"]:
            summary = "[DRY-RUN] " + summary
        self.stdout.write(self.style.SUCCESS(summary))
        if missing:
            self.stdout.write(self.style.WARNING(f"Códigos não encontrados: {', '.join(sorted(set(missing))[:20])}{' ...' if len(missing) > 20 else ''}"))

        if not options["dry_run"]:
            try:
                from estoque.views import _load_plu_mapping  # pylint: disable=import-outside-toplevel

                _load_plu_mapping.cache_clear()  # type: ignore[attr-defined]
            except Exception:
                pass
