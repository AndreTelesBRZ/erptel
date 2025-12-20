from unittest.mock import patch

from django.test import TestCase, Client as TestClient
from django.urls import reverse
from django.contrib.auth.models import User

from companies.services import SefazAPIError
from .models import Client as ClientModel


class ClientModelTest(TestCase):
	def test_create_client(self):
		c = ClientModel.objects.create(person_type='F', document='12345678901', first_name='A', last_name='B', email='a@b.com')
		self.assertIn('A B', str(c))


class ClientViewTest(TestCase):
	def test_index_public(self):
		c = TestClient()
		resp = c.get('/clients/')
		self.assertEqual(resp.status_code, 200)

	def test_create_requires_login(self):
		c = TestClient()
		resp = c.get('/clients/create/')
		self.assertEqual(resp.status_code, 302)

	def test_export_pdf_requires_selection(self):
		user = User.objects.create_user('tester', 'tester@example.com', 'pw123456')
		ClientModel.objects.create(person_type='F', document='98765432109', first_name='Ana', last_name='Silva', email='ana@example.com')

		c = TestClient()
		c.login(username='tester', password='pw123456')
		resp = c.post(reverse('clients:report_pdf'), {'return_url': reverse('clients:index')})
		self.assertEqual(resp.status_code, 302)

	def test_export_pdf_with_selection(self):
		user = User.objects.create_user('tester2', 'tester2@example.com', 'pw123456')
		client_obj = ClientModel.objects.create(person_type='F', document='11122233344', first_name='Bruno', last_name='Souza', email='bruno@example.com')

		c = TestClient()
		c.login(username='tester2', password='pw123456')
		resp = c.post(
			reverse('clients:report_pdf'),
			{'client_ids': [str(client_obj.pk)], 'return_url': reverse('clients:index')}
		)

		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp['Content-Type'], 'application/pdf')
		self.assertGreater(len(resp.content), 200)

	def test_sefaz_lookup_requires_login(self):
		resp = TestClient().get(reverse('clients:sefaz_lookup'), {'cnpj': '12345678000190'})
		self.assertEqual(resp.status_code, 302)

	@patch('clients.views.fetch_company_data_from_sefaz')
	def test_sefaz_lookup_success(self, mock_fetch):
		mock_fetch.return_value = {
			'name': 'Empresa XYZ LTDA',
			'trade_name': 'XYZ',
			'tax_id': '12.345.678/0001-90',
			'email': 'contato@xyz.com',
			'phone': '1133334444',
			'state_registration': '123456789',
			'address': 'Rua das Flores',
			'number': '100',
			'complement': 'Sala 5',
			'district': 'Centro',
			'city': 'São Paulo',
			'state': 'SP',
			'zip_code': '01000-000',
		}
		user = User.objects.create_user('tester3', 'tester3@example.com', 'pw123456')
		c = TestClient()
		c.login(username='tester3', password='pw123456')
		resp = c.get(reverse('clients:sefaz_lookup'), {'cnpj': '12.345.678/0001-90'})
		self.assertEqual(resp.status_code, 200)
		payload = resp.json()['data']
		self.assertEqual(payload['first_name'], 'Empresa XYZ LTDA')
		self.assertEqual(payload['person_type'], 'J')
		self.assertEqual(payload['city'], 'São Paulo')
		mock_fetch.assert_called_once()

	def test_sefaz_lookup_invalid_cnpj(self):
		user = User.objects.create_user('tester4', 'tester4@example.com', 'pw123456')
		c = TestClient()
		c.login(username='tester4', password='pw123456')
		resp = c.get(reverse('clients:sefaz_lookup'), {'cnpj': '123'})
		self.assertEqual(resp.status_code, 400)
		self.assertIn('error', resp.json())

	@patch('clients.views.fetch_company_data_from_sefaz')
	def test_sefaz_lookup_sefaz_error(self, mock_fetch):
		mock_fetch.side_effect = SefazAPIError('Falha na SEFAZ')
		user = User.objects.create_user('tester5', 'tester5@example.com', 'pw123456')
		c = TestClient()
		c.login(username='tester5', password='pw123456')
		resp = c.get(reverse('clients:sefaz_lookup'), {'cnpj': '12345678000190'})
		self.assertEqual(resp.status_code, 502)
		self.assertEqual(resp.json()['error'], 'Falha na SEFAZ')
