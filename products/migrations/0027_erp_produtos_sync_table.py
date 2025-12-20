from django.db import migrations


def create_produtos_sync_table_and_view():
    return """
    DROP VIEW IF EXISTS vw_produtos_sync_preco_estoque;

    CREATE TABLE IF NOT EXISTS erp_produtos_sync (
        codigo VARCHAR(50) NOT NULL,
        descricao_completa TEXT,
        referencia VARCHAR(100),
        secao VARCHAR(20),
        grupo VARCHAR(20),
        subgrupo VARCHAR(20),
        unidade VARCHAR(20),
        ean VARCHAR(50),
        plu VARCHAR(50),
        preco_normal NUMERIC(18, 2),
        preco_promocao1 NUMERIC(18, 2),
        preco_promocao2 NUMERIC(18, 2),
        estoque_disponivel NUMERIC(18, 3),
        loja VARCHAR(20) NOT NULL,
        refplu VARCHAR(50),
        updated_at TIMESTAMPTZ DEFAULT now(),
        PRIMARY KEY (codigo, loja)
    );

    CREATE VIEW vw_produtos_sync_preco_estoque AS
    SELECT
        codigo AS "Codigo",
        descricao_completa AS "DescricaoCompleta",
        referencia AS "Referencia",
        secao AS "Secao",
        grupo AS "Grupo",
        subgrupo AS "Subgrupo",
        unidade AS "Unidade",
        ean AS "EAN",
        plu AS "PLU",
        preco_normal AS "PrecoNormal",
        preco_promocao1 AS "PrecoPromocional1",
        preco_promocao2 AS "PrecoPromocional2",
        estoque_disponivel AS "EstoqueDisponivel",
        loja AS "Loja",
        refplu AS "REFPLU"
    FROM erp_produtos_sync;
    """


class Migration(migrations.Migration):
    dependencies = [
        ('products', '0026_product_plu_code'),
    ]

    operations = [
        migrations.RunSQL(
            create_produtos_sync_table_and_view(),
            reverse_sql="""
            DROP VIEW IF EXISTS vw_produtos_sync_preco_estoque;
            DROP TABLE IF EXISTS erp_produtos_sync;
            """,
        ),
    ]
