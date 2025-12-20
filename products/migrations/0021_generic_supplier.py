from django.db import migrations


GENERIC_SUPPLIER_DOCUMENT = '00000000000000'


def create_generic_supplier(apps, schema_editor):
    Supplier = apps.get_model('products', 'Supplier')
    Supplier.objects.get_or_create(
        document=GENERIC_SUPPLIER_DOCUMENT,
        defaults={
            'name': 'Fornecedor Curinga',
            'person_type': 'J',
            'code': GENERIC_SUPPLIER_DOCUMENT,
            'notes': 'Fornecedor curinga para lançamentos diversos.',
        },
    )


def delete_generic_supplier(apps, schema_editor):
    Supplier = apps.get_model('products', 'Supplier')
    Supplier.objects.filter(document=GENERIC_SUPPLIER_DOCUMENT).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('products', '0020_supplierproductprice_product'),
    ]

    operations = [
        migrations.RunPython(create_generic_supplier, delete_generic_supplier),
    ]
