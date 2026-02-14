from django.db import migrations, models
from django.db.migrations.operations.special import SeparateDatabaseAndState


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0010_pedido_vendedor"),
    ]

    operations = [
        SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE sales_pedido
                        ADD COLUMN IF NOT EXISTS loja_codigo varchar(10) NOT NULL DEFAULT '000001';
                    """,
                    reverse_sql="""
                        ALTER TABLE sales_pedido
                        DROP COLUMN IF EXISTS loja_codigo;
                    """,
                ),
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE sales_itempedido
                        ADD COLUMN IF NOT EXISTS loja_codigo varchar(10) NOT NULL DEFAULT '000001';
                    """,
                    reverse_sql="""
                        ALTER TABLE sales_itempedido
                        DROP COLUMN IF EXISTS loja_codigo;
                    """,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="pedido",
                    name="loja_codigo",
                    field=models.CharField(default="000001", max_length=10),
                ),
                migrations.AddField(
                    model_name="itempedido",
                    name="loja_codigo",
                    field=models.CharField(default="000001", max_length=10),
                ),
            ],
        ),
    ]
