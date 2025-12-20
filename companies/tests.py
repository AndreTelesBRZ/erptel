from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client as TestClient, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Company
from .services import SefazAPIError, fetch_company_data_from_sefaz
from core.models import SefazConfiguration
from core.sefaz.distribution import NFeDistributionResult, NFeDocumentSummary


class CompanyViewTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user('tester', 'tester@example.com', 'pw123456')
		self.client = TestClient()
		self.company = Company.objects.create(
			name='Empresa Base LTDA',
			trade_name='Empresa Base',
			tax_id='12.345.678/0001-99',
		)

	def test_requires_login(self):
		resp = self.client.get(reverse('companies:list'))
		self.assertEqual(resp.status_code, 302)

	def test_create_company(self):
		self.client.login(username='tester', password='pw123456')
		resp = self.client.post(reverse('companies:create'), {
			'name': 'Empresa ABC LTDA',
			'trade_name': 'Empresa ABC',
			'tax_id': '12.345.678/0001-99',
			'is_active': 'on',
		})
		self.assertEqual(resp.status_code, 302)
		company = Company.objects.get(name='Empresa ABC LTDA')
		self.assertEqual(company.code, '12345678000199')
		self.assertEqual(company.tax_id, '12.345.678/0001-99')

	def test_sefaz_lookup_requires_login(self):
		resp = self.client.get(reverse('companies:sefaz_lookup'), {'cnpj': '12345678000190'})
		self.assertEqual(resp.status_code, 302)

	@patch('companies.views.fetch_company_data_from_sefaz')
	def test_sefaz_lookup_success(self, mock_fetch):
		mock_fetch.return_value = {
			'code': 'EMP123',
			'name': 'Empresa XYZ LTDA',
			'trade_name': 'Empresa XYZ',
			'tax_id': '12.345.678/0001-90',
			'state_registration': '123456789',
			'is_active': True,
		}
		self.client.login(username='tester', password='pw123456')
		resp = self.client.get(reverse('companies:sefaz_lookup'), {'cnpj': '12.345.678/0001-90'})
		self.assertEqual(resp.status_code, 200)
		payload = resp.json()
		self.assertIn('data', payload)
		self.assertEqual(payload['data']['name'], 'Empresa XYZ LTDA')
		mock_fetch.assert_called_once_with('12.345.678/0001-90')

	def test_sefaz_lookup_invalid_cnpj(self):
		self.client.login(username='tester', password='pw123456')
		resp = self.client.get(reverse('companies:sefaz_lookup'), {'cnpj': '123'})
		self.assertEqual(resp.status_code, 400)
		self.assertIn('error', resp.json())

	@patch('companies.views.fetch_company_data_from_sefaz')
	def test_sefaz_lookup_sefaz_error(self, mock_fetch):
		self.client.login(username='tester', password='pw123456')
		mock_fetch.side_effect = SefazAPIError('Falha na SEFAZ')
		resp = self.client.get(reverse('companies:sefaz_lookup'), {'cnpj': '12345678000190'})
		self.assertEqual(resp.status_code, 502)
		self.assertEqual(resp.json()['error'], 'Falha na SEFAZ')

	def test_company_nfe_requires_login(self):
		resp = self.client.get(reverse('companies:nfe', args=[self.company.pk]))
		self.assertEqual(resp.status_code, 302)

	def test_company_nfe_without_certificate(self):
		self.client.login(username='tester', password='pw123456')
		resp = self.client.get(reverse('companies:nfe', args=[self.company.pk]))
		self.assertEqual(resp.status_code, 200)
		self.assertContains(resp, 'Certificado digital A1 não configurado')

	def test_company_nfe_json_requires_login(self):
		resp = self.client.get(reverse('companies:nfe_json', args=[self.company.pk]))
		self.assertEqual(resp.status_code, 302)

	def test_company_nfe_json_without_certificate(self):
		self.client.login(username='tester', password='pw123456')
		resp = self.client.get(reverse('companies:nfe_json', args=[self.company.pk]))
		self.assertEqual(resp.status_code, 503)
		self.assertIn('Certificado digital A1', resp.json()['error'])

	@patch('companies.services.fetch_nfe_documents_for_cnpj')
	@patch('companies.services.SefazConfiguration.load')
	def test_company_nfe_success(self, mock_config_load, mock_fetch):
		self.client.login(username='tester', password='pw123456')
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
			total_value=Decimal('123.45'),
			raw_xml='<resNFe/>',
		)
		mock_fetch.return_value = NFeDistributionResult(
			status_code='138',
			status_message='Documentos localizados',
			last_nsu='000000000000123',
			max_nsu='000000000000456',
			documents=[doc],
		)

		resp = self.client.get(reverse('companies:nfe', args=[self.company.pk]))
		self.assertEqual(resp.status_code, 200)
		self.assertContains(resp, 'Documentos localizados')
		self.assertContains(resp, 'Fornecedor Teste')
		mock_fetch.assert_called_once()

	@patch('companies.services.fetch_nfe_documents_for_cnpj')
	@patch('companies.services.SefazConfiguration.load')
	def test_company_nfe_json_success(self, mock_config_load, mock_fetch):
		self.client.login(username='tester', password='pw123456')
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
			total_value=Decimal('222.33'),
			raw_xml='<resNFe/>',
		)
		mock_fetch.return_value = NFeDistributionResult(
			status_code='138',
			status_message='Documentos localizados',
			last_nsu='000000000000123',
			max_nsu='000000000000456',
			documents=[doc],
		)

		resp = self.client.get(reverse('companies:nfe_json', args=[self.company.pk]), {'last_nsu': '123'})
		self.assertEqual(resp.status_code, 200)
		payload = resp.json()
		self.assertEqual(payload['status_code'], '138')
		self.assertEqual(payload['count'], 1)
		self.assertEqual(payload['documents'][0]['issuer_name'], 'Fornecedor Teste')
		mock_fetch.assert_called_once()

	@patch('companies.services.fetch_nfe_documents_for_cnpj')
	@patch('companies.services.SefazConfiguration.load')
	def test_company_nfe_invalid_access_key(self, mock_config_load, mock_fetch):
		self.client.login(username='tester', password='pw123456')
		config = SimpleNamespace(certificate_file=SimpleNamespace(name='certificates/test.pfx'), certificate_password='senha')
		mock_config_load.return_value = config
		resp = self.client.get(reverse('companies:nfe', args=[self.company.pk]), {'access_key': '123'})
		self.assertEqual(resp.status_code, 200)
		self.assertContains(resp, '44 dígitos')
		mock_fetch.assert_not_called()

	@patch('companies.services.fetch_nfe_documents_for_cnpj')
	@patch('companies.services.SefazConfiguration.load')
	def test_company_nfe_json_invalid_access_key(self, mock_config_load, mock_fetch):
		self.client.login(username='tester', password='pw123456')
		config = SimpleNamespace(certificate_file=SimpleNamespace(name='certificates/test.pfx'), certificate_password='senha')
		mock_config_load.return_value = config
		resp = self.client.get(reverse('companies:nfe_json', args=[self.company.pk]), {'access_key': '123'})
		self.assertEqual(resp.status_code, 400)
		self.assertIn('44 dígitos', resp.json()['error'])
		mock_fetch.assert_not_called()

	@patch('companies.services.fetch_nfe_documents_for_cnpj')
	@patch('companies.services.SefazConfiguration.load')
	def test_company_nfe_json_invalid_date(self, mock_config_load, mock_fetch):
		self.client.login(username='tester', password='pw123456')
		config = SimpleNamespace(certificate_file=SimpleNamespace(name='certificates/test.pfx'), certificate_password='senha')
		mock_config_load.return_value = config
		resp = self.client.get(reverse('companies:nfe_json', args=[self.company.pk]), {'issued_from': 'data-invalida'})
		self.assertEqual(resp.status_code, 400)
		self.assertIn('formato', resp.json()['error'])
		mock_fetch.assert_not_called()

	@patch('companies.services.requests.get')
	def test_fetch_company_uses_configuration(self, mock_get):
		config = SefazConfiguration.load()
		config.base_url = 'https://sefaz.example/api'
		config.token = 'token123'
		config.timeout = 5
		config.save()

		mock_response = mock_get.return_value
		mock_response.status_code = 200
		mock_response.json.return_value = {
			'cnpj': '12345678000190',
			'razao_social': 'Empresa Teste',
		}

		data = fetch_company_data_from_sefaz('12.345.678/0001-90')
		self.assertEqual(data['name'], 'Empresa Teste')
		mock_get.assert_called_once_with(
			'https://sefaz.example/api/cnpj/12345678000190',
			headers={'Accept': 'application/json', 'Authorization': 'Bearer token123'},
			timeout=5,
		)
