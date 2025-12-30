# api/serializers.py
from decimal import Decimal

from rest_framework import serializers

from .models import ProdutoSync, PlanoPagamentoCliente, Loja
from sales.models import Pedido, ItemPedido
from products.models import Product
from clients.models import Client, ClienteSync


def _only_digits(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


class ProdutoSyncSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProdutoSync
        fields = "__all__"


class ClienteSyncSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClienteSync
        fields = [
            "cliente_codigo",
            "cliente_status",
            "cliente_razao_social",
            "cliente_nome_fantasia",
            "cliente_cnpj_cpf",
            "cliente_tipo_pf_pj",
            "cliente_endereco",
            "cliente_numero",
            "cliente_bairro",
            "cliente_cidade",
            "cliente_uf",
            "cliente_cep",
            "cliente_telefone1",
            "cliente_telefone2",
            "cliente_email",
            "cliente_inscricao_municipal",
            "vendedor_codigo",
            "vendedor_nome",
            "ultima_venda_data",
            "ultima_venda_valor",
            "updated_at",
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["cliente_cnpj_cpf"] = _only_digits(data.get("cliente_cnpj_cpf"))
        return data


class PlanoPagamentoClienteSerializer(serializers.ModelSerializer):
    CLICOD = serializers.CharField(source="cliente_codigo")
    PLACOD = serializers.CharField(source="plano_codigo")
    PLADES = serializers.CharField(source="plano_descricao", allow_blank=True, required=False)
    PLAENT = serializers.DecimalField(
        max_digits=18,
        decimal_places=6,
        required=False,
        allow_null=True,
        write_only=True,
    )
    PLAINTPRI = serializers.IntegerField(
        source="dias_primeira_parcela",
        required=False,
        allow_null=True,
    )
    PLAINTPAR = serializers.IntegerField(
        source="dias_entre_parcelas",
        required=False,
        allow_null=True,
    )
    PLANUMPAR = serializers.IntegerField(
        source="parcelas",
        required=False,
        allow_null=True,
    )
    PLAVLRMIN = serializers.DecimalField(
        source="valor_minimo",
        max_digits=18,
        decimal_places=6,
        required=False,
        allow_null=True,
    )
    PLAVLRACR = serializers.DecimalField(
        source="valor_acrescimo",
        max_digits=18,
        decimal_places=6,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = PlanoPagamentoCliente
        fields = [
            "CLICOD",
            "PLACOD",
            "PLADES",
            "PLAENT",
            "PLAINTPRI",
            "PLAINTPAR",
            "PLANUMPAR",
            "PLAVLRMIN",
            "PLAVLRACR",
        ]

    def validate(self, attrs):
        cliente = (attrs.get("cliente_codigo") or "").strip()
        plano = (attrs.get("plano_codigo") or "").strip()
        descricao = (attrs.get("plano_descricao") or "").strip()
        if not cliente:
            raise serializers.ValidationError({"CLICOD": "CLICOD é obrigatório."})
        if not plano:
            raise serializers.ValidationError({"PLACOD": "PLACOD é obrigatório."})
        if not descricao:
            raise serializers.ValidationError({"PLADES": "PLADES é obrigatório."})
        return attrs


class LojaSerializer(serializers.ModelSerializer):
    LOJCOD = serializers.CharField(source="codigo")
    AGEDES = serializers.CharField(source="razao_social", allow_blank=True, required=False)
    AGEFAN = serializers.CharField(source="nome_fantasia", allow_blank=True, required=False)
    AGECGCCPF = serializers.CharField(source="cnpj_cpf", allow_blank=True, required=False)
    AGECGFRG = serializers.CharField(source="ie_rg", allow_blank=True, required=False)
    AGEPFPJ = serializers.CharField(source="tipo_pf_pj", allow_blank=True, required=False)
    AGETEL1 = serializers.CharField(source="telefone1", allow_blank=True, required=False)
    AGETEL2 = serializers.CharField(source="telefone2", allow_blank=True, required=False)
    AGEEND = serializers.CharField(source="endereco", allow_blank=True, required=False)
    AGEBAI = serializers.CharField(source="bairro", allow_blank=True, required=False)
    AGENUM = serializers.CharField(source="numero", allow_blank=True, required=False)
    AGECPL = serializers.CharField(source="complemento", allow_blank=True, required=False)
    AGECEP = serializers.CharField(source="cep", allow_blank=True, required=False)
    AGECORELE = serializers.CharField(source="email", allow_blank=True, required=False)
    AGECID = serializers.CharField(source="cidade", allow_blank=True, required=False)
    AGEEST = serializers.CharField(source="estado", allow_blank=True, required=False)

    class Meta:
        model = Loja
        fields = [
            "LOJCOD",
            "AGEDES",
            "AGEFAN",
            "AGECGCCPF",
            "AGECGFRG",
            "AGEPFPJ",
            "AGETEL1",
            "AGETEL2",
            "AGEEND",
            "AGEBAI",
            "AGENUM",
            "AGECPL",
            "AGECEP",
            "AGECORELE",
            "AGECID",
            "AGEEST",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["AGECGCCPF"] = _only_digits(data.get("AGECGCCPF"))
        return data


class ItemPedidoSerializer(serializers.ModelSerializer):
    # Usado na criação (write)
    codigo_produto = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        source="produto",
        write_only=True,
    )
    # Representação (read)
    produto_id = serializers.IntegerField(source="produto_id", read_only=True)
    produto_codigo = serializers.CharField(source="produto.code", read_only=True)
    produto_nome = serializers.CharField(source="produto.name", read_only=True)
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = ItemPedido
        fields = [
            "codigo_produto",
            "produto_id",
            "produto_codigo",
            "produto_nome",
            "quantidade",
            "valor_unitario",
            "subtotal",
        ]

    @staticmethod
    def get_subtotal(obj) -> Decimal:
        qty = obj.quantidade or Decimal("0")
        unit = obj.valor_unitario or Decimal("0")
        return qty * unit


class PedidoSerializer(serializers.ModelSerializer):
    itens = ItemPedidoSerializer(many=True)
    cliente_id = serializers.PrimaryKeyRelatedField(
        queryset=Client.objects.all(),
        source="cliente",
    )
    loja_codigo = serializers.CharField(required=False, allow_blank=True)
    total_itens = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Pedido
        fields = [
            "id",
            "data_criacao",
            "data_recebimento",
            "total",
            "cliente_id",
            "loja_codigo",
            "itens",
            "total_itens",
        ]
        read_only_fields = ["id", "data_recebimento"]

    def validate(self, attrs):
        itens_data = attrs.get("itens") or []
        if not itens_data:
            raise serializers.ValidationError({"itens": "Inclua pelo menos um item no pedido."})

        loja_codigo = attrs.get("loja_codigo")
        if loja_codigo is not None:
            loja_codigo = loja_codigo.strip()
            if not loja_codigo:
                attrs.pop("loja_codigo", None)
            else:
                attrs["loja_codigo"] = loja_codigo

        total_itens = sum(
            (item_data.get("quantidade") or Decimal("0")) * (item_data.get("valor_unitario") or Decimal("0"))
            for item_data in itens_data
        )

        total_enviado = attrs.get("total")
        if total_enviado is None:
            attrs["total"] = total_itens
        else:
            try:
                total_decimal = Decimal(total_enviado)
            except Exception:
                raise serializers.ValidationError({"total": "Informe um valor numérico para o total."})

            if total_decimal.quantize(Decimal("0.01")) != total_itens.quantize(Decimal("0.01")):
                raise serializers.ValidationError(
                    {"total": f"O total informado ({total_decimal}) é diferente da soma dos itens ({total_itens})."}
                )
            attrs["total"] = total_decimal
        return attrs

    def create(self, validated_data):
        itens_data = validated_data.pop("itens", [])
        loja_codigo = validated_data.get("loja_codigo") or None
        pedido = Pedido.objects.create(**validated_data)
        if loja_codigo:
            for item_data in itens_data:
                item_data.setdefault("loja_codigo", loja_codigo)
        ItemPedido.objects.bulk_create(
            [ItemPedido(pedido=pedido, **item_data) for item_data in itens_data]
        )
        return pedido

    @staticmethod
    def get_total_itens(obj) -> Decimal:
        return sum((item.quantidade or Decimal("0")) * (item.valor_unitario or Decimal("0")) for item in obj.itens.all())

    def to_representation(self, instance):
        """
        Quando usado para leitura, devolve dados resumidos do cliente e itens já aninhados.
        """
        data = super().to_representation(instance)
        cliente = getattr(instance, "cliente", None)
        data["cliente"] = None
        if cliente:
            data["cliente"] = {
                "id": cliente.pk,
                "codigo": cliente.code,
                "nome": f"{cliente.first_name} {cliente.last_name}".strip(),
                "documento": _only_digits(cliente.document),
                "email": cliente.email,
                "telefone": cliente.phone,
            }
        data["itens"] = ItemPedidoSerializer(instance.itens.all(), many=True, context=self.context).data
        return data


class PedidoStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Pedido.Status.choices)
