from django.db import models

class ProdutoSync(models.Model):
    codigo = models.CharField(primary_key=True, max_length=50, db_column="Codigo")
    descricao = models.TextField(null=True, blank=True, db_column="DescricaoCompleta")
    referencia = models.CharField(max_length=100, null=True, blank=True, db_column="Referencia")
    secao = models.CharField(max_length=20, null=True, blank=True, db_column="Secao")
    grupo = models.CharField(max_length=20, null=True, blank=True, db_column="Grupo")
    subgrupo = models.CharField(max_length=20, null=True, blank=True, db_column="Subgrupo")
    unidade = models.CharField(max_length=20, null=True, blank=True, db_column="Unidade")
    ean = models.CharField(max_length=50, null=True, blank=True, db_column="EAN")
    plu = models.CharField(max_length=50, null=True, blank=True, db_column="PLU")
    preco_normal = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True, db_column="PrecoNormal")
    preco_promocional_1 = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True, db_column="PrecoPromocional1")
    preco_promocional_2 = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True, db_column="PrecoPromocional2")
    estoque_disponivel = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True, db_column="EstoqueDisponivel")
    loja = models.CharField(max_length=20, null=True, blank=True, db_column="Loja")
    ref_plu = models.CharField(max_length=50, null=True, blank=True, db_column="REFPLU")
    row_hash = models.TextField(null=True, blank=True, db_column="RowHash")

    class Meta:
        db_table = "vw_produtos_sync_preco_estoque"
        managed = False
        app_label = "api"


class PlanoPagamentoCliente(models.Model):
    cliente_codigo = models.CharField(max_length=20)
    plano_codigo = models.CharField(max_length=20)
    descricao = models.CharField(max_length=255, blank=True)
    entrada_percentual = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    intervalo_primeira_parcela = models.IntegerField(null=True, blank=True)
    intervalo_parcelas = models.IntegerField(null=True, blank=True)
    quantidade_parcelas = models.IntegerField(null=True, blank=True)
    valor_acrescimo = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    valor_minimo = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "plano_pagamentos_clientes"
        constraints = [
            models.UniqueConstraint(
                fields=["cliente_codigo", "plano_codigo"],
                name="uniq_plano_pagamentos_clientes",
            )
        ]
        indexes = [
            models.Index(fields=["cliente_codigo"], name="idx_plano_pag_cli"),
        ]
        app_label = "api"


class Loja(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    razao_social = models.CharField(max_length=255, blank=True)
    nome_fantasia = models.CharField(max_length=255, blank=True)
    cnpj_cpf = models.CharField(max_length=20, blank=True)
    ie_rg = models.CharField(max_length=50, blank=True)
    tipo_pf_pj = models.CharField(max_length=4, blank=True)
    telefone1 = models.CharField(max_length=50, blank=True)
    telefone2 = models.CharField(max_length=50, blank=True)
    endereco = models.CharField(max_length=255, blank=True)
    bairro = models.CharField(max_length=100, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    complemento = models.CharField(max_length=100, blank=True)
    cep = models.CharField(max_length=20, blank=True)
    email = models.CharField(max_length=255, blank=True)
    cidade = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=5, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "erp_lojas"
        indexes = [
            models.Index(fields=["codigo"], name="idx_erp_lojas_codigo"),
        ]
        app_label = "api"
