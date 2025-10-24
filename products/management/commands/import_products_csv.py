import argparse
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from products.utils import import_products_from_file


class Command(BaseCommand):
    help = 'Import products from a CSV file (delimiter ; , decimals with comma)'

    def add_arguments(self, parser):
        parser.add_argument('csvfile', type=str, help='Path to CSV file')
        parser.add_argument('--encoding', type=str, default='utf-8', help='File encoding')

    def handle(self, *args, **options):
        csv_path = Path(options['csvfile'])
        if not csv_path.exists():
            raise CommandError(f"File not found: {csv_path}")

        created, updated, messages = import_products_from_file(csv_path)
        for m in messages:
            self.stdout.write(self.style.SUCCESS(m))
        self.stdout.write(self.style.SUCCESS(f"Import finished. Created: {created}, Updated: {updated}"))
