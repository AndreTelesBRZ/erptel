from decimal import Decimal
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from companies.models import Company
from core.models import SefazConfiguration
from core.sefaz.distribution import NFeDistributionResult, NFeDocumentSummary
from clients.models import Client
from products.models import Product
from sales.models import Pedido, ItemPedido
from django.test import override_settings


class SefazConfigurationAPITests(APITestCase):
	def setUp(self):
		self.user = User.objects.create_user('tester', 'tester@example.com', 'pw123456')
		self.client.login(username='tester', password='pw123456')

	def test_get_configuration(self):
		config = SefazConfiguration.load()
		config.base_url = 'https://example.com'
		config.timeout = 20
		config.save()
		url = reverse('api-sefaz-config')
		resp = self.client.get(url)
		self.assertEqual(resp.status_code, status.HTTP_200_OK)
		payload = resp.json()
		self.assertEqual(payload['base_url'], 'https://example.com')
		self.assertEqual(payload['timeout'], 20)

	def test_update_configuration(self):
		url = reverse('api-sefaz-config')
		resp = self.client.put(url, {
			'base_url': 'https://sefaz.example/api',
			'token': 'abc123',
			'timeout': 15,
			'environment': 'production',
		})
		self.assertEqual(resp.status_code, status.HTTP_200_OK)
		config = SefazConfiguration.load()
		self.assertEqual(config.base_url, 'https://sefaz.example/api')
		self.assertEqual(config.token, 'abc123')
		self.assertEqual(config.timeout, 15)

	def test_requires_authentication(self):
		self.client.logout()
		url = reverse('api-sefaz-config')
		resp = self.client.get(url)
		self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class CompanyNFeAPITests(APITestCase):
	def setUp(self):
		self.user = User.objects.create_user('tester', 'tester@example.com', 'pw123456')
		self.client.login(username='tester', password='pw123456')
		self.company = Company.objects.create(name='Empresa Base', trade_name='Base', tax_id='12.345.678/0001-99')

	def test_requires_certificate(self):
		url = reverse('api-company-nfe', args=[self.company.pk])
		resp = self.client.get(url)
		self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
		self.assertIn('Certificado digital A1', resp.json()['error'])

	@patch('companies.services.fetch_nfe_documents_for_cnpj')
	@patch('companies.services.SefazConfiguration.load')
	def test_returns_documents(self, mock_config_load, mock_fetch):
		config = SimpleNamespace(certificate_file=SimpleNamespace(name='certificates/test.pfx'), certificate_password='senha')
		mock_config_load.return_value = config
		doc = NFeDocumentSummary(
			nsu='000000000000123',
			schema='resNFe_v1.01',
			document_type='resNFe',
			access_key='12345678901234567890123456789012345678901234',
			issuer_tax_id='12345678000190',
			issuer_name='Fornecedor Teste',
			issue_datetime=timezone.now(),
			authorization_datetime=timezone.now(),
			total_value=Decimal('125.10'),
			raw_xml='<resNFe/>',
		)
		mock_fetch.return_value = NFeDistributionResult(
			status_code='138',
			status_message='Documentos localizados',
			last_nsu='000000000000123',
			max_nsu='000000000000456',
			documents=[doc],
		)
		url = reverse('api-company-nfe', args=[self.company.pk])
		resp = self.client.get(url, {'last_nsu': '123'})
		self.assertEqual(resp.status_code, status.HTTP_200_OK)
		body = resp.json()
		self.assertEqual(body['status_code'], '138')
		self.assertEqual(body['count'], 1)
		self.assertEqual(body['documents'][0]['issuer_name'], 'Fornecedor Teste')
		mock_fetch.assert_called_once()

	@patch('companies.services.fetch_nfe_documents_for_cnpj')
	@patch('companies.services.SefazConfiguration.load')
	def test_date_filters(self, mock_config_load, mock_fetch):
		config = SimpleNamespace(certificate_file=SimpleNamespace(name='certificates/test.pfx'), certificate_password='senha')
		mock_config_load.return_value = config
		now = timezone.now()
		older = now - timedelta(days=2)
		newer = now - timedelta(hours=1)
		doc_old = NFeDocumentSummary(
			nsu='1',
			schema='resNFe_v1.01',
			document_type='resNFe',
			access_key='1' * 44,
			issuer_tax_id='12345678000190',
			issuer_name='Fornecedor 1',
			issue_datetime=older,
			authorization_datetime=older,
			total_value=Decimal('10.00'),
			raw_xml='<resNFe/>',
		)
		doc_new = NFeDocumentSummary(
			nsu='2',
			schema='resNFe_v1.01',
			document_type='resNFe',
			access_key='2' * 44,
			issuer_tax_id='12345678000190',
			issuer_name='Fornecedor 2',
			issue_datetime=newer,
			authorization_datetime=newer,
			total_value=Decimal('20.00'),
			raw_xml='<resNFe/>',
		)
		mock_fetch.return_value = NFeDistributionResult(
			status_code='138',
			status_message='Documentos localizados',
			last_nsu='000000000000123',
			max_nsu='000000000000456',
			documents=[doc_old, doc_new],
		)
		url = reverse('api-company-nfe', args=[self.company.pk])
		resp = self.client.get(url, {
			'issued_from': (now - timedelta(days=1)).isoformat(),
		})
		self.assertEqual(resp.status_code, status.HTTP_200_OK)
		body = resp.json()
		self.assertEqual(body['count'], 1)
		self.assertEqual(body['documents'][0]['issuer_name'], 'Fornecedor 2')


@override_settings(APP_INTEGRATION_TOKEN="super-secreto")
class PedidoIntegrationAPITests(APITestCase):
	def setUp(self):
		self.client.defaults['HTTP_X_APP_TOKEN'] = "super-secreto"
		self.client_obj = Client.objects.create(
			person_type=Client.PersonType.INDIVIDUAL,
			code="12345678900",
			document="12345678900",
			first_name="Cliente",
			last_name="Teste",
			email="cliente@test.com",
		)
		self.product = Product.objects.create(name="Produto Teste", price=Decimal('10.00'), code="P1")

	def test_requires_token(self):
		url = reverse('pedidos-venda-list')
		payload = {
			"data_criacao": timezone.now().isoformat(),
			"total": "10.00",
			"cliente_id": self.client_obj.id,
			"itens": [
				{"codigo_produto": self.product.id, "quantidade": "1", "valor_unitario": "10.00"}
			],
		}
		self.client.defaults.pop('HTTP_X_APP_TOKEN')
		resp = self.client.post(url, payload, format='json')
		self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

	def test_create_and_list_pedidos_venda(self):
		url = reverse('pedidos-venda-list')
		payload = {
			"data_criacao": timezone.now().isoformat(),
			"total": "20.00",
			"cliente_id": self.client_obj.id,
			"itens": [
				{"codigo_produto": self.product.id, "quantidade": "2", "valor_unitario": "10.00"}
			],
		}
		resp = self.client.post(url, payload, format='json')
		self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
		body = resp.json()
		self.assertIsNotNone(body.get("id"))
		self.assertEqual(body["total"], "20.00")
		self.assertEqual(len(body["itens"]), 1)
		self.assertEqual(body["itens"][0]["subtotal"], "20.00")

		# Listagem inclui o pedido criado
		list_resp = self.client.get(url)
		self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
		self.assertGreaterEqual(list_resp.json().get("count"), 1)

	def test_patch_pedido_venda_is_blocked(self):
		pedido = Pedido.objects.create(
			cliente=self.client_obj,
			data_criacao=timezone.now(),
			total=Decimal('10.00'),
		)
		ItemPedido.objects.create(
			pedido=pedido,
			produto=self.product,
			quantidade=Decimal('1'),
			valor_unitario=Decimal('10.00'),
		)
		url = reverse('pedidos-venda-detail', args=[pedido.id])
		resp = self.client.patch(url, {"plano_codigo": "X1"}, format='json')
		self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

	def test_filters_by_recebimento(self):
		hoje = timezone.now()
		ontem = hoje - timedelta(days=1)
		corte = hoje - timedelta(hours=12)
		pedido_antigo = Pedido.objects.create(
			cliente=self.client_obj,
			data_criacao=ontem,
			total=Decimal('5.00'),
		)
		Pedido.objects.filter(pk=pedido_antigo.pk).update(data_recebimento=ontem)
		ItemPedido.objects.create(
			pedido=pedido_antigo,
			produto=self.product,
			quantidade=Decimal('1'),
			valor_unitario=Decimal('5.00'),
		)
		pedido_recente = Pedido.objects.create(
			cliente=self.client_obj,
			data_criacao=hoje,
			data_recebimento=hoje,
			total=Decimal('10.00'),
		)
		ItemPedido.objects.create(
			pedido=pedido_recente,
			produto=self.product,
			quantidade=Decimal('1'),
			valor_unitario=Decimal('10.00'),
		)

		url = reverse('pedidos-venda-list')
		resp = self.client.get(url, {'recebido_depois': corte.isoformat()})
		self.assertEqual(resp.status_code, status.HTTP_200_OK)
		results = resp.json()["results"]
		self.assertTrue(any(p["id"] == pedido_recente.id for p in results))
		self.assertFalse(any(p["id"] == pedido_antigo.id for p in results))

	def test_detail_contains_required_order_schema(self):
		pedido = Pedido.objects.create(
			cliente=self.client_obj,
			data_criacao=timezone.now(),
			total=Decimal('35.00'),
			status=Pedido.Status.ORCAMENTO,
			pagamento_status=Pedido.PaymentStatus.AGUARDANDO,
			forma_pagamento='Boleto',
			plano_codigo='30D',
			frete_modalidade=Pedido.FreightMode.CIF,
		)
		ItemPedido.objects.create(
			pedido=pedido,
			produto=self.product,
			quantidade=Decimal('3'),
			valor_unitario=Decimal('10.00'),
		)
		pedido.recalcular_total(save=True)
		pedido.refresh_from_db()

		resp = self.client.get(reverse('pedidos-venda-detail', args=[pedido.id]))
		self.assertEqual(resp.status_code, status.HTTP_200_OK)
		body = resp.json()

		self.assertEqual(body["id"], pedido.id)
		self.assertIn("identificadores", body)
		self.assertEqual(body["identificadores"]["erp_id"], pedido.id)
		self.assertIn("cliente", body)
		self.assertEqual(body["cliente"]["id"], self.client_obj.id)
		self.assertIn("pagamento", body)
		self.assertEqual(body["pagamento"]["forma"], "Boleto")
		self.assertIn("frete", body)
		self.assertEqual(body["frete"]["modalidade"], Pedido.FreightMode.CIF)
		self.assertIn("itens", body)
		self.assertEqual(len(body["itens"]), 1)
		self.assertEqual(body["itens"][0]["subtotal"], "30.00")
		self.assertEqual(body["quantidade_itens"], 1)
		self.assertEqual(body["quantidade_total_itens"], 3.0)
		self.assertIn("totais", body)
		self.assertEqual(body["totais"]["subtotal"], 30.0)
		self.assertEqual(body["totais"]["total"], 30.0)

	def test_pedido_detail_reflects_erp_changes_on_next_read(self):
		pedido = Pedido.objects.create(
			cliente=self.client_obj,
			data_criacao=timezone.now(),
			total=Decimal('10.00'),
			status=Pedido.Status.ORCAMENTO,
		)
		item = ItemPedido.objects.create(
			pedido=pedido,
			produto=self.product,
			quantidade=Decimal('1'),
			valor_unitario=Decimal('10.00'),
		)
		pedido.recalcular_total(save=True)

		url = reverse('pedidos-venda-detail', args=[pedido.id])
		before = self.client.get(url)
		self.assertEqual(before.status_code, status.HTTP_200_OK)
		self.assertEqual(before.json()["totais"]["total"], 10.0)

		item.quantidade = Decimal('4')
		item.valor_unitario = Decimal('12.00')
		item.save()
		pedido.status = Pedido.Status.EM_SEPARACAO
		pedido.pagamento_status = Pedido.PaymentStatus.FATURA_A_VENCER
		pedido.recalcular_total(save=True)
		pedido.save(update_fields=["status", "pagamento_status", "updated_at"])

		after = self.client.get(url)
		self.assertEqual(after.status_code, status.HTTP_200_OK)
		payload = after.json()
		self.assertEqual(payload["status"], Pedido.Status.EM_SEPARACAO)
		self.assertEqual(payload["pagamento"]["status"], Pedido.PaymentStatus.FATURA_A_VENCER)
		self.assertEqual(payload["itens"][0]["quantidade"], "4.00")
		self.assertEqual(payload["itens"][0]["valor_unitario"], "12.00")
		self.assertEqual(payload["totais"]["total"], 48.0)

	def test_get_pedido_detail_alias_endpoint(self):
		pedido = Pedido.objects.create(
			cliente=self.client_obj,
			data_criacao=timezone.now(),
			total=Decimal('10.00'),
		)
		ItemPedido.objects.create(
			pedido=pedido,
			produto=self.product,
			quantidade=Decimal('1'),
			valor_unitario=Decimal('10.00'),
		)
		resp = self.client.get(reverse('api-pedidos-detail', args=[pedido.id]))
		self.assertEqual(resp.status_code, status.HTTP_200_OK)
		body = resp.json()
		self.assertEqual(body["id"], pedido.id)
		self.assertEqual(body["quantidade_itens"], 1)
		self.assertIn("totais", body)
