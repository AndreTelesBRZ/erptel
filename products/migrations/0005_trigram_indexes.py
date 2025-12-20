from django.db import migrations


def enable_trgm_and_indexes(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor != 'postgresql':
        return
    with conn.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        # Products indexes for trigram search
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS products_product_name_trgm
            ON products_product USING gin (name gin_trgm_ops);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS products_product_description_trgm
            ON products_product USING gin (description gin_trgm_ops);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS products_product_code_trgm
            ON products_product USING gin (code gin_trgm_ops);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS products_product_gtin_trgm
            ON products_product USING gin (gtin gin_trgm_ops);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS products_product_supplier_code_trgm
            ON products_product USING gin (supplier_code gin_trgm_ops);
        """)


def drop_trgm_indexes(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor != 'postgresql':
        return
    with conn.cursor() as cursor:
        cursor.execute("DROP INDEX IF EXISTS products_product_name_trgm;")
        cursor.execute("DROP INDEX IF EXISTS products_product_description_trgm;")
        cursor.execute("DROP INDEX IF EXISTS products_product_code_trgm;")
        cursor.execute("DROP INDEX IF EXISTS products_product_gtin_trgm;")
        cursor.execute("DROP INDEX IF EXISTS products_product_supplier_code_trgm;")


class Migration(migrations.Migration):
    dependencies = [
        ('products', '0004_productimage_image_alter_productimage_url'),
    ]

    operations = [
        migrations.RunPython(enable_trgm_and_indexes, reverse_code=drop_trgm_indexes),
    ]

