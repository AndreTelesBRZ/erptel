from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0006_fix_plano_pagamento_table_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="planopagamentocliente",
            name="dias_primeira_parcela",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
