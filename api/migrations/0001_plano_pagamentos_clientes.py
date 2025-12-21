from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="PlanoPagamentoCliente",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cliente_codigo", models.CharField(max_length=20)),
                ("plano_codigo", models.CharField(max_length=20)),
                ("descricao", models.CharField(blank=True, max_length=255)),
                ("entrada_percentual", models.DecimalField(blank=True, decimal_places=6, max_digits=18, null=True)),
                ("intervalo_primeira_parcela", models.IntegerField(blank=True, null=True)),
                ("intervalo_parcelas", models.IntegerField(blank=True, null=True)),
                ("quantidade_parcelas", models.IntegerField(blank=True, null=True)),
                ("valor_acrescimo", models.DecimalField(blank=True, decimal_places=6, max_digits=18, null=True)),
                ("valor_minimo", models.DecimalField(blank=True, decimal_places=6, max_digits=18, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "plano_pagamentos_clientes",
            },
        ),
        migrations.AddConstraint(
            model_name="planopagamentocliente",
            constraint=models.UniqueConstraint(
                fields=("cliente_codigo", "plano_codigo"),
                name="uniq_plano_pagamentos_clientes",
            ),
        ),
        migrations.AddIndex(
            model_name="planopagamentocliente",
            index=models.Index(fields=["cliente_codigo"], name="idx_plano_pag_cli"),
        ),
    ]
