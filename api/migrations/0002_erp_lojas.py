from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0001_plano_pagamentos_clientes"),
    ]

    operations = [
        migrations.CreateModel(
            name="Loja",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codigo", models.CharField(max_length=20, unique=True)),
                ("razao_social", models.CharField(blank=True, max_length=255)),
                ("nome_fantasia", models.CharField(blank=True, max_length=255)),
                ("cnpj_cpf", models.CharField(blank=True, max_length=20)),
                ("ie_rg", models.CharField(blank=True, max_length=50)),
                ("tipo_pf_pj", models.CharField(blank=True, max_length=4)),
                ("telefone1", models.CharField(blank=True, max_length=50)),
                ("telefone2", models.CharField(blank=True, max_length=50)),
                ("endereco", models.CharField(blank=True, max_length=255)),
                ("bairro", models.CharField(blank=True, max_length=100)),
                ("numero", models.CharField(blank=True, max_length=20)),
                ("complemento", models.CharField(blank=True, max_length=100)),
                ("cep", models.CharField(blank=True, max_length=20)),
                ("email", models.CharField(blank=True, max_length=255)),
                ("cidade", models.CharField(blank=True, max_length=100)),
                ("estado", models.CharField(blank=True, max_length=5)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "erp_lojas",
            },
        ),
        migrations.AddIndex(
            model_name="loja",
            index=models.Index(fields=["codigo"], name="idx_erp_lojas_codigo"),
        ),
    ]
