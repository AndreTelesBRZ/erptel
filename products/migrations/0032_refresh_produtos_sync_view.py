from django.db import migrations


def forward_sql():
    return """
    DROP VIEW IF EXISTS vw_produtos_sync_preco_estoque;
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
        custo AS "Custo",
        estoque_disponivel AS "EstoqueDisponivel",
        loja AS "Loja",
        refplu AS "REFPLU",
        row_hash AS "RowHash"
    FROM erp_produtos_sync;
    """


def reverse_sql():
    return """
    DROP VIEW IF EXISTS vw_produtos_sync_preco_estoque;
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
        preco_promocao2 AS "PrecoPromocao2",
        custo AS "Custo",
        estoque_disponivel AS "EstoqueDisponivel",
        loja AS "Loja",
        refplu AS "REFPLU",
        row_hash AS "RowHash"
    FROM erp_produtos_sync;
    """


class Migration(migrations.Migration):
    dependencies = [
        ('products', '0031_add_cost_to_produtos_sync'),
    ]

    operations = [
        migrations.RunSQL(forward_sql(), reverse_sql()),
    ]
