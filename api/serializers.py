# api/serializers.py
from decimal import Decimal

from rest_framework import serializers

from .models import ProdutoSync
from sales.models import Pedido, ItemPedido
from products.models import Product
from clients.models import Client, ClienteSync


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
    total_itens = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Pedido
        fields = ["id", "data_criacao", "data_recebimento", "total", "cliente_id", "itens", "total_itens"]
        read_only_fields = ["id", "data_recebimento"]

    def validate(self, attrs):
        itens_data = attrs.get("itens") or []
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
                "documento": cliente.document,
                "email": cliente.email,
                "telefone": cliente.phone,
            }
        data["itens"] = ItemPedidoSerializer(instance.itens.all(), many=True, context=self.context).data
        return data
