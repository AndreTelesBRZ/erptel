from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_sefazconfiguration_environment"),
    ]

    operations = [
        migrations.RunSQL(
            """
            CREATE TABLE IF NOT EXISTS erp_inadimplencia (
                id BIGSERIAL PRIMARY KEY,
                cod_loja VARCHAR(10) NOT NULL,
                cod_vendedor VARCHAR(10),
                num_titulo VARCHAR(30) NOT NULL,
                cod_cliente VARCHAR(20) NOT NULL,
                razao_social TEXT,
                nome_fantasia TEXT,
                cpf_cnpj VARCHAR(20),
                tipo_doc VARCHAR(10),
                documento_tipo TEXT,
                cidade TEXT,
                vencimento DATE,
                vencimento_real DATE,
                valor_devedor NUMERIC(15, 2),
                hash_registro TEXT,
                last_sync TIMESTAMP DEFAULT now()
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_erp_inadimplencia
            ON erp_inadimplencia (cod_loja, num_titulo);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS ux_erp_inadimplencia;
            DROP TABLE IF EXISTS erp_inadimplencia;
            """,
        ),
    ]
