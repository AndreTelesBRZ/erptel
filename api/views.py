from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404

from rest_framework import viewsets, permissions, status, mixins
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token

from .models import ProdutoSync
from .serializers import ProdutoSyncSerializer, PedidoSerializer, ClienteSyncSerializer
from core.forms import SefazConfigurationForm
from core.models import SefazConfiguration
from companies.models import Company
from companies.services import (
	prepare_company_nfe_query,
	serialize_nfe_document,
	has_configured_sefaz_certificate,
)
from .permissions import HasAppToken
from sales.models import Pedido
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from clients.models import ClienteSync


class CustomAuthToken(ObtainAuthToken):
	def post(self, request, *args, **kwargs):
		serializer = self.serializer_class(data=request.data, context={"request": request})
		serializer.is_valid(raise_exception=True)
		user = serializer.validated_data["user"]
		token, created = Token.objects.get_or_create(user=user)
		return Response(
			{
				"token": token.key,
				"user_id": user.pk,
				"email": user.email,
				"username": user.get_username(),
			}
		)


class ProdutoSyncViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = ProdutoSync.objects.all().order_by("codigo")
	serializer_class = ProdutoSyncSerializer
	search_fields = ["codigo", "descricao", "ean", "referencia", "plu"]
	filterset_fields = ["codigo", "ean", "plu", "loja"]
	ordering_fields = [
		"codigo",
		"descricao",
		"referencia",
		"plu",
		"preco_normal",
		"preco_promocional_1",
		"preco_promocional_2",
		"estoque_disponivel",
		"loja",
		"row_hash",
	]


class ClienteSyncViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = ClienteSync.objects.all().order_by("cliente_codigo")
	serializer_class = ClienteSyncSerializer
	permission_classes = [HasAppToken]
	pagination_class = None
	search_fields = [
		"cliente_codigo",
		"cliente_razao_social",
		"cliente_nome_fantasia",
		"cliente_cnpj_cpf",
		"cliente_email",
		"cliente_telefone1",
		"cliente_telefone2",
		"vendedor_nome",
	]
	filterset_fields = [
		"cliente_codigo",
		"cliente_status",
		"cliente_cnpj_cpf",
		"cliente_uf",
		"vendedor_codigo",
	]
	ordering_fields = [
		"cliente_codigo",
		"cliente_razao_social",
		"cliente_nome_fantasia",
		"cliente_cnpj_cpf",
		"ultima_venda_data",
		"ultima_venda_valor",
		"updated_at",
	]


class SefazConfigurationAPIView(APIView):
	permission_classes = [permissions.IsAuthenticated]

	def get(self, request):
		config = SefazConfiguration.load()
		return Response(self._serialize_config(config))

	def put(self, request):
		return self._handle_submit(request)

	def patch(self, request):
		return self._handle_submit(request)

	def _handle_submit(self, request):
		config = SefazConfiguration.load()
		form = SefazConfigurationForm(request.data, request.FILES, instance=config)
		if form.is_valid():
			cfg = form.save(commit=False)
			cfg.updated_by = request.user
			try:
				cfg.save()
			except ValidationError as exc:
				for field, messages in exc.message_dict.items():
					if field in form.fields:
						for message in messages:
							form.add_error(field, message)
					else:
						for message in messages:
							form.add_error(None, message)
				return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)
			return Response(self._serialize_config(cfg))
		return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

	@staticmethod
	def _serialize_config(config: SefazConfiguration) -> dict:
		return {
			'base_url': config.base_url,
			'token': config.token,
			'timeout': config.timeout,
			'environment': config.environment,
			'certificate': {
				'is_configured': has_configured_sefaz_certificate(config),
				'subject': config.certificate_subject,
				'serial_number': config.certificate_serial_number,
				'valid_from': config.certificate_valid_from.isoformat() if config.certificate_valid_from else None,
				'valid_until': config.certificate_valid_until.isoformat() if config.certificate_valid_until else None,
				'uploaded_at': config.certificate_uploaded_at.isoformat() if config.certificate_uploaded_at else None,
			},
		}


class CompanyNFeAPIView(APIView):
	permission_classes = [permissions.IsAuthenticated]

	def get(self, request, pk: int):
		company = get_object_or_404(Company, pk=pk)
		params, result, error, sefaz_ready = prepare_company_nfe_query(company, request.query_params)
		if not sefaz_ready:
			return Response({'error': error, 'params': params}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
		if error:
			return Response({'error': error, 'params': params}, status=status.HTTP_400_BAD_REQUEST)
		if not result:
			return Response({'message': 'Nenhuma resposta foi retornada pela SEFAZ.', 'params': params})
		documents = [serialize_nfe_document(doc) for doc in result.documents]
		return Response({
			'company': {
				'id': company.pk,
				'name': company.name,
				'tax_id': company.tax_id,
			},
			'params': params,
			'status_code': result.status_code,
			'status_message': result.status_message,
			'last_nsu': result.last_nsu,
			'max_nsu': result.max_nsu,
			'count': len(documents),
			'documents': documents,
		})


class PedidoViewSet(mixins.CreateModelMixin,
					mixins.ListModelMixin,
					mixins.RetrieveModelMixin,
					viewsets.GenericViewSet):
	permission_classes = [HasAppToken]
	serializer_class = PedidoSerializer
	queryset = (
		Pedido.objects
		.select_related('cliente')
		.prefetch_related('itens__produto')
		.order_by('-data_recebimento', '-id')
	)

	def get_queryset(self):
		qs = super().get_queryset()
		params = self.request.query_params

		cliente_id = params.get('cliente_id')
		if cliente_id:
			qs = qs.filter(cliente_id=cliente_id)

		cliente_codigo = params.get('cliente_codigo')
		if cliente_codigo:
			qs = qs.filter(cliente__code=cliente_codigo)

		after = self._parse_dt(params.get('recebido_depois')) or self._parse_dt(params.get('depois'))
		if after:
			qs = qs.filter(data_recebimento__gte=after)

		before = self._parse_dt(params.get('recebido_ate')) or self._parse_dt(params.get('ate'))
		if before:
			qs = qs.filter(data_recebimento__lte=before)

		created_after = self._parse_dt(params.get('criado_depois'))
		if created_after:
			qs = qs.filter(data_criacao__gte=created_after)

		created_before = self._parse_dt(params.get('criado_ate'))
		if created_before:
			qs = qs.filter(data_criacao__lte=created_before)

		return qs

	def create(self, request, *args, **kwargs):
		serializer = self.get_serializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		self.perform_create(serializer)
		read_serializer = PedidoSerializer(serializer.instance, context=self.get_serializer_context())
		headers = self.get_success_headers(read_serializer.data)
		return Response(read_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

	@staticmethod
	def _parse_dt(value):
		if not value:
			return None
		dt = parse_datetime(value)
		if dt and timezone.is_naive(dt):
			dt = timezone.make_aware(dt)
		return dt


class ReceberPedidoView(APIView):
	permission_classes = [HasAppToken]

	@transaction.atomic
	def post(self, request):
		serializer = PedidoSerializer(data=request.data)
		if serializer.is_valid():
			pedido = serializer.save()
			return Response(
				{
					"id": pedido.id,
					"status": "sucesso",
					"mensagem": "Pedido recebido com sucesso",
					"pedido": PedidoSerializer(pedido, context={"request": request}).data,
				},
				status=status.HTTP_201_CREATED,
			)
		return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
