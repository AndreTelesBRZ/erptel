from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0009_pedido_status_pagamento_frete'),
    ]

    operations = [
        migrations.AddField(
            model_name='pedido',
            name='vendedor_codigo',
            field=models.CharField(blank=True, max_length=50, verbose_name='Código do vendedor'),
        ),
        migrations.AddField(
            model_name='pedido',
            name='vendedor_nome',
            field=models.CharField(blank=True, max_length=150, verbose_name='Nome do vendedor'),
        ),
    ]
