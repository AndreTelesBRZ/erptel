# api/serializers.py
from decimal import Decimal

from rest_framework import serializers

from .models import ProdutoSync, Loja
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
    produto_id = serializers.IntegerField(read_only=True)
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
    def get_subtotal(obj) -> str:
        qty = obj.quantidade or Decimal("0")
        unit = obj.valor_unitario or Decimal("0")
        return f"{(qty * unit):.2f}"


class PedidoSerializer(serializers.ModelSerializer):
    itens = ItemPedidoSerializer(many=True)
    cliente_id = serializers.PrimaryKeyRelatedField(
        queryset=Client.objects.all(),
        source="cliente",
    )
    total_itens = serializers.SerializerMethodField(read_only=True)
    quantidade_itens = serializers.SerializerMethodField(read_only=True)
    quantidade_total_itens = serializers.SerializerMethodField(read_only=True)
    totais = serializers.SerializerMethodField(read_only=True)
    identificadores = serializers.SerializerMethodField(read_only=True)
    pagamento = serializers.SerializerMethodField(read_only=True)
    frete = serializers.SerializerMethodField(read_only=True)
    status_info = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Pedido
        fields = [
            "id",
            "data_criacao",
            "data_recebimento",
            "updated_at",
            "total",
            "status",
            "pagamento_status",
            "frete_modalidade",
            "forma_pagamento",
            "plano_codigo",
            "cliente_id",
            "itens",
            "total_itens",
            "quantidade_itens",
            "quantidade_total_itens",
            "totais",
            "identificadores",
            "pagamento",
            "frete",
            "status_info",
        ]
        read_only_fields = ["id", "data_recebimento", "updated_at"]

    def validate(self, attrs):
        itens_data = attrs.get("itens")
        if itens_data is None:
            return attrs

        if not itens_data:
            raise serializers.ValidationError({"itens": "Inclua pelo menos um item no pedido."})

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
        pedido = Pedido.objects.create(**validated_data)
        ItemPedido.objects.bulk_create(
            [
                ItemPedido(
                    pedido=pedido,
                    produto=item_data.get("produto"),
                    produto_codigo=getattr(item_data.get("produto"), "code", "") or "",
                    quantidade=item_data.get("quantidade"),
                    valor_unitario=item_data.get("valor_unitario"),
                    subtotal=(item_data.get("quantidade") or Decimal("0")) * (item_data.get("valor_unitario") or Decimal("0")),
                )
                for item_data in itens_data
            ]
        )
        pedido.recalcular_total(save=True)
        return pedido

    @staticmethod
    def get_total_itens(obj) -> Decimal:
        return sum((item.quantidade or Decimal("0")) * (item.valor_unitario or Decimal("0")) for item in obj.itens.all())

    @staticmethod
    def get_quantidade_itens(obj) -> int:
        return obj.itens.count()

    @staticmethod
    def get_quantidade_total_itens(obj) -> Decimal:
        return sum((item.quantidade or Decimal("0")) for item in obj.itens.all())

    @staticmethod
    def get_totais(obj) -> dict:
        subtotal = sum((item.subtotal or Decimal("0")) for item in obj.itens.all())
        total = obj.total or Decimal("0")
        if total >= subtotal:
            frete = total - subtotal
            descontos = Decimal("0")
        else:
            frete = Decimal("0")
            descontos = subtotal - total
        return {
            "subtotal": subtotal,
            "descontos": descontos,
            "frete": frete,
            "total": total,
        }

    @staticmethod
    def get_identificadores(obj) -> dict:
        return {
            "id": obj.pk,
            "erp_id": obj.pk,
            "uuid": None,
        }

    @staticmethod
    def get_pagamento(obj) -> dict:
        return {
            "status": obj.pagamento_status,
            "status_display": obj.get_pagamento_status_display(),
            "forma": obj.forma_pagamento or "",
            "plano_codigo": obj.plano_codigo or "",
        }

    @staticmethod
    def get_frete(obj) -> dict:
        totais = PedidoSerializer.get_totais(obj)
        return {
            "modalidade": obj.frete_modalidade,
            "modalidade_display": obj.get_frete_modalidade_display(),
            "valor": totais["frete"],
            "loja_codigo": obj.loja_codigo,
        }

    @staticmethod
    def get_status_info(obj) -> dict:
        return {
            "status": obj.status,
            "status_display": obj.get_status_display(),
        }

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
                "inscricao_estadual": cliente.state_registration,
                "endereco": {
                    "logradouro": cliente.address,
                    "numero": cliente.number,
                    "complemento": cliente.complement,
                    "bairro": cliente.district,
                    "cidade": cliente.city,
                    "estado": cliente.state,
                    "cep": cliente.zip_code,
                },
            }
        data["itens"] = ItemPedidoSerializer(instance.itens.all(), many=True, context=self.context).data
        return data
