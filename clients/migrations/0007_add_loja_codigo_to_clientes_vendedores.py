from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0006_auto_20251224_1737'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE erp_clientes_vendedores
                    ADD COLUMN IF NOT EXISTS loja_codigo VARCHAR(10);
                CREATE INDEX IF NOT EXISTS idx_erp_clientes_vendedores_loja
                    ON erp_clientes_vendedores (loja_codigo);
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
