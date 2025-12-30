from django.db import migrations


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cur:
        cur.execute("SELECT to_regclass('public.plano_pagamentos_clientes');")
        plural = cur.fetchone()[0]
        cur.execute("SELECT to_regclass('public.plano_pagamento_cliente');")
        singular = cur.fetchone()[0]

        if plural and not singular:
            cur.execute(
                "ALTER TABLE plano_pagamentos_clientes RENAME TO plano_pagamento_cliente;"
            )
            singular = "plano_pagamento_cliente"

        if singular and not plural:
            cur.execute(
                """
                CREATE OR REPLACE VIEW plano_pagamentos_clientes AS
                SELECT * FROM plano_pagamento_cliente;
                """
            )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cur:
        cur.execute("SELECT to_regclass('public.plano_pagamentos_clientes');")
        plural = cur.fetchone()[0]
        cur.execute("SELECT to_regclass('public.plano_pagamento_cliente');")
        singular = cur.fetchone()[0]

        if plural and singular:
            cur.execute("DROP VIEW plano_pagamentos_clientes;")


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0005_rename_plano_pagamento_cliente_table"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
