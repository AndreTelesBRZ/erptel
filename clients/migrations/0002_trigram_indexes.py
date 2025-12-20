from django.db import migrations


def enable_trgm_and_indexes(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor != 'postgresql':
        return
    with conn.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS clients_client_first_name_trgm
            ON clients_client USING gin (first_name gin_trgm_ops);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS clients_client_last_name_trgm
            ON clients_client USING gin (last_name gin_trgm_ops);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS clients_client_email_trgm
            ON clients_client USING gin (email gin_trgm_ops);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS clients_client_phone_trgm
            ON clients_client USING gin (phone gin_trgm_ops);
        """)


def drop_trgm_indexes(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor != 'postgresql':
        return
    with conn.cursor() as cursor:
        cursor.execute("DROP INDEX IF EXISTS clients_client_first_name_trgm;")
        cursor.execute("DROP INDEX IF EXISTS clients_client_last_name_trgm;")
        cursor.execute("DROP INDEX IF EXISTS clients_client_email_trgm;")
        cursor.execute("DROP INDEX IF EXISTS clients_client_phone_trgm;")


class Migration(migrations.Migration):
    dependencies = [
        ('clients', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(enable_trgm_and_indexes, reverse_code=drop_trgm_indexes),
    ]

