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
