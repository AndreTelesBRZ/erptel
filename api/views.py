from django.core.exceptions import ValidationError
import logging
from django.shortcuts import get_object_or_404

from rest_framework import viewsets, permissions, status, mixins
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token

from .models import ProdutoSync, PlanoPagamentoCliente, Loja
from .serializers import (
	ProdutoSyncSerializer,
	PedidoSerializer,
	PedidoStatusSerializer,
	ClienteSyncSerializer,
	PlanoPagamentoClienteSerializer,
	LojaSerializer,
)
from core.forms import SefazConfigurationForm
from core.models import SefazConfiguration
from companies.models import Company
from companies.services import (
	prepare_company_nfe_query,
	serialize_nfe_document,
	has_configured_sefaz_certificate,
)
from .permissions import HasAppToken, HasAppTokenOrAuthenticated
from sales.models import Pedido
from django.db import transaction, models
from decimal import Decimal, InvalidOperation
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from clients.models import ClienteSync
from django.conf import settings

logger = logging.getLogger("api.planos_pagamento")


def _is_admin_user(user) -> bool:
	if not user or not user.is_authenticated:
		return False
	if user.is_superuser or user.is_staff:
		return True
	profile = getattr(user, "access_profile", None)
	if not profile:
		return False
	return profile.roles.filter(code="administration").exists()


def _is_system_request(request) -> bool:
	expected_token = getattr(settings, "APP_INTEGRATION_TOKEN", None)
	if not expected_token:
		return False
	return request.headers.get("X-App-Token") == expected_token


def _get_vendor_code(user) -> str | None:
	salesperson = getattr(user, "salesperson_profile", None)
	return getattr(salesperson, "code", None)


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
	permission_classes = [HasAppTokenOrAuthenticated]
	authentication_classes = [SessionAuthentication]
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

	def get_queryset(self):
		qs = super().get_queryset()
		request = getattr(self, "request", None)
		loja_codigo = getattr(request, "loja_codigo", None)
		if loja_codigo:
			return qs.filter(loja=loja_codigo)
		return qs


class ClienteSyncViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = ClienteSync.objects.all().order_by("cliente_codigo")
	serializer_class = ClienteSyncSerializer
	permission_classes = [HasAppTokenOrAuthenticated]
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

	def get_queryset(self):
		qs = super().get_queryset()
		request = getattr(self, "request", None)
		if request is None:
			return qs.none()
		loja_codigo = getattr(request, "loja_codigo", None)
		if _is_system_request(request):
			return qs.filter(loja_codigo=loja_codigo) if loja_codigo else qs
		user = getattr(request, "user", None)
		if _is_admin_user(user):
			return qs.filter(loja_codigo=loja_codigo) if loja_codigo else qs
		if not user or not user.is_authenticated:
			raise PermissionDenied("Usuário não autenticado")
		vendor_code = _get_vendor_code(user)
		if not vendor_code:
			raise PermissionDenied("Vendedor não identificado")
		qs = qs.filter(vendedor_codigo=vendor_code)
		if loja_codigo:
			qs = qs.filter(loja_codigo=loja_codigo)
		return qs


class LojaViewSet(viewsets.ReadOnlyModelViewSet):
	queryset = Loja.objects.all().order_by("codigo")
	serializer_class = LojaSerializer
	permission_classes = [HasAppToken]
	pagination_class = None
	search_fields = [
		"codigo",
		"razao_social",
		"nome_fantasia",
		"cnpj_cpf",
		"cidade",
		"estado",
	]
	filterset_fields = [
		"codigo",
		"cidade",
		"estado",
	]
	ordering_fields = [
		"codigo",
		"razao_social",
		"nome_fantasia",
		"cidade",
		"estado",
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


class PlanoPagamentoClienteAPIView(APIView):
	permission_classes = [HasAppToken]

	def get(self, request, cliente_codigo: str = ""):
		cliente_codigo = (cliente_codigo or request.query_params.get("cliente_codigo") or "").strip()
		if not cliente_codigo:
			return Response({"detail": "Informe o código do cliente."}, status=status.HTTP_400_BAD_REQUEST)

		qs = PlanoPagamentoCliente.objects.filter(cliente_codigo=cliente_codigo).order_by("plano_codigo")
		data = PlanoPagamentoClienteSerializer(qs, many=True).data
		forma_pagamento = (request.query_params.get("forma_pagamento") or "").strip().lower()

		if forma_pagamento:
			def _format_legend(item):
				parcelas = item.get("PLANUMPAR") or 1
				dias = item.get("PLAINTPAR") or 0
				valor_minimo = item.get("PLAVLRMIN")
				if valor_minimo is None:
					valor_minimo_str = "0.00"
				else:
					try:
						valor_minimo_str = f"{Decimal(str(valor_minimo)):.2f}"
					except (InvalidOperation, ValueError):
						valor_minimo_str = "0.00"
				return f"Parcelas: {parcelas} • Dias entre parcelas: {dias} • Valor mínimo: R$ {valor_minimo_str}"

			def _apply_label(item, parcelas):
				descricao = (item.get("PLADES") or "").strip()
				if parcelas > 1:
					label = f"{descricao} {parcelas}x".strip() if descricao else f"{parcelas}x"
				else:
					label = "(1x)"
				item["PLADES"] = label
				item["PLALEG"] = _format_legend(item)
				return item

			if forma_pagamento in {"pix", "dinheiro"}:
				escolhido = next((item for item in data if (item.get("PLANUMPAR") or 1) <= 1), None)
				if not escolhido and data:
					escolhido = data[0]
				if escolhido:
					escolhido["PLANUMPAR"] = 1
					escolhido["PLAINTPAR"] = 0 if escolhido.get("PLAINTPAR") is None else escolhido["PLAINTPAR"]
					data = [_apply_label(escolhido, 1)]
				else:
					data = []
			elif forma_pagamento == "boleto":
				filtrados = [item for item in data if (item.get("PLANUMPAR") or 1) > 1]
				data = [_apply_label(item, item.get("PLANUMPAR") or 1) for item in filtrados]
		return Response(
			{
				"cliente_codigo": cliente_codigo,
				"total": len(data),
				"data": data,
			}
		)


class PlanoPagamentoClienteSyncAPIView(APIView):
	permission_classes = [HasAppToken]

	def post(self, request):
		payload = request.data
		if isinstance(payload, dict) and "data" in payload:
			payload = payload["data"]
		if not isinstance(payload, list):
			return Response({"detail": "Envie uma lista de planos."}, status=status.HTTP_400_BAD_REQUEST)

		valid_items = []
		for item in payload:
			serializer = PlanoPagamentoClienteSerializer(data=item)
			if not serializer.is_valid():
				logger.warning("Plano inválido: %s", serializer.errors)
				continue
			data = dict(serializer.validated_data)
			data.pop("PLAENT", None)
			if data.get("parcelas") is None:
				data["parcelas"] = 1
			if data.get("dias_primeira_parcela") is None:
				data["dias_primeira_parcela"] = 0
			if data.get("dias_entre_parcelas") is None:
				data["dias_entre_parcelas"] = 0
			if data.get("valor_minimo") is None:
				data["valor_minimo"] = 0
			if data.get("valor_acrescimo") is None:
				data["valor_acrescimo"] = 0
			valid_items.append(data)

		now = timezone.now()
		plans = [PlanoPagamentoCliente(updated_at=now, **item) for item in valid_items]
		keys = {(p.cliente_codigo, p.plano_codigo) for p in plans}
		existentes = set(
			PlanoPagamentoCliente.objects.filter(
				models.Q(
					*[
						models.Q(cliente_codigo=cliente, plano_codigo=plano)
						for cliente, plano in keys
					]
				)
			).values_list("cliente_codigo", "plano_codigo")
		) if keys else set()

		inseridos = len(keys - existentes)
		atualizados = len(keys & existentes)

		if plans:
			PlanoPagamentoCliente.objects.bulk_create(
				plans,
				update_conflicts=True,
				unique_fields=["cliente_codigo", "plano_codigo"],
				update_fields=[
					"plano_descricao",
					"parcelas",
					"dias_primeira_parcela",
					"dias_entre_parcelas",
					"valor_acrescimo",
					"valor_minimo",
					"updated_at",
				],
			)

		return Response(
			{
				"status": "ok",
				"total_recebidos": len(payload),
				"inseridos": inseridos,
				"atualizados": atualizados,
			}
		)


class LojaSyncAPIView(APIView):
	permission_classes = [HasAppToken]

	def post(self, request):
		payload = request.data
		if isinstance(payload, dict) and "data" in payload:
			payload = payload["data"]
		if not isinstance(payload, list):
			return Response({"detail": "Envie uma lista de lojas."}, status=status.HTTP_400_BAD_REQUEST)

		serializer = LojaSerializer(data=payload, many=True)
		serializer.is_valid(raise_exception=True)

		now = timezone.now()
		lojas = [Loja(updated_at=now, **item) for item in serializer.validated_data]
		if lojas:
			Loja.objects.bulk_create(
				lojas,
				update_conflicts=True,
				unique_fields=["codigo"],
				update_fields=[
					"razao_social",
					"nome_fantasia",
					"cnpj_cpf",
					"ie_rg",
					"tipo_pf_pj",
					"telefone1",
					"telefone2",
					"endereco",
					"bairro",
					"numero",
					"complemento",
					"cep",
					"email",
					"cidade",
					"estado",
					"updated_at",
				],
			)

		return Response({"status": "ok", "total": len(lojas)})


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


class PedidoStatusUpdateView(APIView):
	permission_classes = [HasAppToken]

	def put(self, request, pk):
		pedido = get_object_or_404(Pedido, pk=pk)
		serializer = PedidoStatusSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		pedido.status = serializer.validated_data["status"]
		pedido.save(update_fields=["status"])
		return Response(
			{
				"id": pedido.id,
				"status": pedido.status,
				"status_display": pedido.get_status_display(),
			},
			status=status.HTTP_200_OK,
		)


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
