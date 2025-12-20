from django.core.management.base import BaseCommand
from products.models import Product


class Command(BaseCommand):
    help = "Delete products whose code starts with the given prefix. Example: manage.py delete_products_by_code_prefix 000"

    def add_arguments(self, parser):
        parser.add_argument('prefix', type=str, help="Prefix to match at the start of code")
        parser.add_argument('--dry-run', action='store_true', help="Only show what would be deleted")

    def handle(self, *args, **options):
        prefix = options['prefix']
        dry_run = options['dry_run']

        qs = Product.objects.filter(code__startswith=prefix)
        count = qs.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS("No products found with code starting with '%s'." % prefix))
            return

        if dry_run:
            # Show a short preview
            preview = list(qs.values_list('id', 'code', 'name')[:20])
            self.stdout.write("%d products would be deleted. Showing first 20:" % count)
            for pid, code, name in preview:
                self.stdout.write(f"- id={pid} code={code} name={name}")
            return

        deleted = count
        qs.delete()
        self.stdout.write(self.style.WARNING("Deleted %d products with code starting with '%s'." % (deleted, prefix)))

