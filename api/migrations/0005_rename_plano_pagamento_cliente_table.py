from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0004_produtosync_and_more"),
    ]

    operations = [
        migrations.AlterModelTable(
            name="planopagamentocliente",
            table="plano_pagamento_cliente",
        ),
    ]
