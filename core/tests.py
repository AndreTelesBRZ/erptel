from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from companies.models import Company
from clients.models import Client
from products.models import (
    Product,
    PriceAdjustmentBatch,
    PriceAdjustmentItem,
    Supplier,
    Brand,
    Category,
    Department,
    Volume,
    UnitOfMeasure,
    ProductGroup,
    ProductSubGroup,
)
from sales.models import Quote, QuoteItem

from .models import EmailConfiguration, SefazConfiguration, UserAccessProfile, UserRole


class SefazConfigurationTests(TestCase):
	def test_load_creates_singleton(self):
		config = SefazConfiguration.load()
		self.assertIsNotNone(config.pk)
		self.assertEqual(SefazConfiguration.objects.count(), 1)
		config_again = SefazConfiguration.load()
		self.assertEqual(config.pk, config_again.pk)

	def test_settings_view_requires_login(self):
		resp = self.client.get(reverse('core:settings_sefaz'))
		self.assertEqual(resp.status_code, 302)

	def test_settings_view_updates_config(self):
		user = User.objects.create_user('tester', 'tester@example.com', 'pw123456')
		self.client.login(username='tester', password='pw123456')
		resp = self.client.post(reverse('core:settings_sefaz'), {
			'base_url': 'https://sefaz.example/api',
			'token': 'abc123',
			'timeout': '7',
		})
		self.assertEqual(resp.status_code, 302)
		config = SefazConfiguration.load()
		self.assertEqual(config.base_url, 'https://sefaz.example/api')
		self.assertEqual(config.token, 'abc123')
		self.assertEqual(config.timeout, 7)
		self.assertEqual(config.updated_by, user)

	def test_logout_view_redirects(self):
		user = User.objects.create_user('tester2', 'tester2@example.com', 'pw123456')
		self.client.login(username='tester2', password='pw123456')
		resp = self.client.post(reverse('logout'))
		self.assertRedirects(resp, reverse('login'))
		resp2 = self.client.get(reverse('dashboard'))
		self.assertEqual(resp2.status_code, 302)

	def test_access_settings_requires_login(self):
		resp = self.client.get(reverse('core:settings_access'))
		self.assertEqual(resp.status_code, 302)

	def test_access_settings_update(self):
		admin = User.objects.create_user('admin', 'admin@example.com', 'pw123456')
		user = User.objects.create_user('agent', 'agent@example.com', 'pw123456')
		company = Company.objects.create(name='Empresa A', trade_name='Empresa A', tax_id='12.345.678/0001-99')
		self.client.login(username='admin', password='pw123456')
		profile, _ = UserAccessProfile.objects.get_or_create(user=user)
		resp = self.client.post(reverse('core:settings_access_edit', args=[user.pk]), {
			'roles': [str(UserRole.objects.get(code='seller').pk)],
			'can_manage_products': 'on',
			'can_manage_clients': '',
			'can_manage_sales': 'on',
			'can_manage_purchases': '',
			'can_manage_finance': 'on',
			'companies': [str(company.pk)],
			'notes': 'Acesso restrito',
		})
		self.assertRedirects(resp, reverse('core:settings_access'))
		profile.refresh_from_db()
		self.assertTrue(profile.can_manage_products)
		self.assertFalse(profile.can_manage_clients)
		self.assertEqual(profile.updated_by, admin)
		self.assertEqual(list(profile.companies.all()), [company])
		self.assertEqual(list(profile.roles.values_list('code', flat=True)), ['seller'])

	def test_access_settings_create_user(self):
		admin = User.objects.create_user('admin', 'admin@example.com', 'pw123456')
		self.client.login(username='admin', password='pw123456')
		role = UserRole.objects.get(code='seller')
		company = Company.objects.create(name='Empresa B', trade_name='Empresa B', tax_id='98.765.432/0001-11')
		resp = self.client.post(reverse('core:settings_access_create'), {
			'username': 'newuser',
			'first_name': 'Novo',
			'last_name': 'Usuário',
			'email': 'novo@example.com',
			'is_active': 'on',
			'password1': 'Fort3Senha!',
			'password2': 'Fort3Senha!',
			'roles': [str(role.pk)],
			'can_manage_products': 'on',
			'can_manage_clients': 'on',
			'can_manage_sales': '',
			'can_manage_purchases': '',
			'can_manage_finance': '',
			'companies': [str(company.pk)],
			'notes': 'Usuário temporário',
		})
		self.assertRedirects(resp, reverse('core:settings_access'))
		created = User.objects.get(username='newuser')
		self.assertEqual(created.email, 'novo@example.com')
		self.assertTrue(created.is_active)
		profile = created.access_profile
		self.assertEqual(list(profile.roles.values_list('code', flat=True)), ['seller'])
		self.assertTrue(profile.can_manage_products)
		self.assertTrue(profile.can_manage_clients)
		self.assertFalse(profile.can_manage_sales)
		self.assertEqual(list(profile.companies.all()), [company])


class EmailConfigurationTests(TestCase):
	def test_load_creates_singleton(self):
		config = EmailConfiguration.load()
		self.assertIsNotNone(config.pk)
		self.assertEqual(EmailConfiguration.objects.count(), 1)
		config_again = EmailConfiguration.load()
		self.assertEqual(config.pk, config_again.pk)

	def test_settings_view_requires_login(self):
		resp = self.client.get(reverse('core:settings_email'))
		self.assertEqual(resp.status_code, 302)

	def test_settings_view_updates_config(self):
		user = User.objects.create_user('mailer', 'mailer@example.com', 'pw123456')
		self.client.login(username='mailer', password='pw123456')
		resp = self.client.post(reverse('core:settings_email'), {
			'smtp_host': 'smtp.example.com',
			'smtp_port': '587',
			'smtp_username': 'mailer',
			'smtp_password': 'secret123',
			'smtp_use_tls': 'on',
			'default_from_email': 'noreply@example.com',
			'incoming_protocol': 'imap',
			'incoming_host': 'imap.example.com',
			'incoming_port': '993',
			'incoming_username': 'mailer',
			'incoming_password': 'secret123',
			'incoming_use_ssl': 'on',
		})
		self.assertRedirects(resp, reverse('core:settings_email'))
		config = EmailConfiguration.load()
		self.assertEqual(config.smtp_host, 'smtp.example.com')
		self.assertEqual(config.smtp_port, 587)
		self.assertTrue(config.smtp_use_tls)
		self.assertFalse(config.smtp_use_ssl)
		self.assertEqual(config.default_from_email, 'noreply@example.com')
		self.assertEqual(config.incoming_protocol, 'imap')
		self.assertEqual(config.incoming_host, 'imap.example.com')
		self.assertEqual(config.incoming_port, 993)
		self.assertTrue(config.incoming_use_ssl)
		self.assertFalse(config.incoming_use_tls)
		self.assertEqual(config.updated_by, user)

	def test_cannot_select_both_encryptions(self):
		user = User.objects.create_user('mailer2', 'mailer2@example.com', 'pw123456')
		self.client.login(username='mailer2', password='pw123456')
		resp = self.client.post(reverse('core:settings_email'), {
			'smtp_host': 'smtp.example.com',
			'smtp_port': '587',
			'smtp_username': 'mailer',
			'smtp_password': 'secret123',
			'smtp_use_tls': 'on',
			'smtp_use_ssl': 'on',
			'default_from_email': 'noreply@example.com',
			'incoming_protocol': 'imap',
			'incoming_host': 'imap.example.com',
			'incoming_port': '993',
			'incoming_username': 'mailer',
			'incoming_password': 'secret123',
			'incoming_use_ssl': 'on',
			'incoming_use_tls': 'on',
		})
		self.assertEqual(resp.status_code, 200)
		self.assertContains(resp, 'Selecione apenas uma opção de criptografia para envio.')
		self.assertContains(resp, 'Selecione apenas uma opção de criptografia para recebimento.')

	@patch('django.core.mail.EmailMessage.send', return_value=1)
	def test_test_email_success(self, send_mock):
		config = EmailConfiguration.load()
		config.smtp_host = 'smtp.example.com'
		config.smtp_port = 587
		config.smtp_username = 'mailer@example.com'
		config.smtp_password = 'secret123'
		config.smtp_use_tls = True
		config.smtp_use_ssl = False
		config.default_from_email = 'noreply@example.com'
		config.save()
		user = User.objects.create_user('tester', 'tester@example.com', 'pw123456')
		self.client.login(username='tester', password='pw123456')
		resp = self.client.post(reverse('core:settings_email'), {
			'action': 'test',
			'recipient': 'dest@example.com',
		})
		self.assertRedirects(resp, reverse('core:settings_email'))
		send_mock.assert_called_once()

	def test_test_email_requires_host(self):
		EmailConfiguration.objects.all().delete()
		config = EmailConfiguration.load()
		config.smtp_host = ''
		config.save()
		user = User.objects.create_user('tester2', 'tester2@example.com', 'pw123456')
		self.client.login(username='tester2', password='pw123456')
		resp = self.client.post(reverse('core:settings_email'), {
			'action': 'test',
			'recipient': 'dest@example.com',
		})
		self.assertEqual(resp.status_code, 200)
		test_form = resp.context['test_form']
		self.assertIn('Configure o servidor SMTP antes de enviar um teste.', test_form.non_field_errors())

	@patch('django.core.mail.EmailMessage.send', side_effect=Exception('boom'))
	def test_test_email_handles_exception(self, send_mock):
		config = EmailConfiguration.load()
		config.smtp_host = 'smtp.example.com'
		config.smtp_port = 587
		config.smtp_username = 'mailer@example.com'
		config.smtp_password = 'secret123'
		config.smtp_use_tls = True
		config.smtp_use_ssl = False
		config.default_from_email = 'noreply@example.com'
		config.save()
		user = User.objects.create_user('tester3', 'tester3@example.com', 'pw123456')
		self.client.login(username='tester3', password='pw123456')
		resp = self.client.post(reverse('core:settings_email'), {
			'action': 'test',
			'recipient': 'dest@example.com',
		})
		self.assertEqual(resp.status_code, 200)
		test_form = resp.context['test_form']
		self.assertIn('Não foi possível enviar o e-mail de teste: boom', test_form.non_field_errors())
		send_mock.assert_called_once()


class LookupTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user('lookup', 'lookup@example.com', 'pw123456')
		self.client.login(username='lookup', password='pw123456')

	def test_lookup_requires_login(self):
		self.client.logout()
		resp = self.client.get(reverse('core:lookup', args=['clients']))
		self.assertEqual(resp.status_code, 302)

	def test_lookup_clients_returns_results(self):
		Client.objects.create(
			person_type=Client.PersonType.INDIVIDUAL,
			document='12345678901',
			email='cliente@example.com',
			first_name='Cliente',
			last_name='Teste',
		)
		resp = self.client.get(reverse('core:lookup', args=['clients']), {'q': 'Cliente'})
		self.assertEqual(resp.status_code, 200)
		payload = resp.json()
		self.assertIn('results', payload)
		self.assertTrue(any(item['name'].startswith('Cliente') for item in payload['results']))

	def test_lookup_products_includes_stock(self):
		Product.objects.create(name='Produto Especial', price=Decimal('15.00'), stock=Decimal('7.50'))
		resp = self.client.get(reverse('core:lookup', args=['products']), {'q': 'Especial'})
		self.assertEqual(resp.status_code, 200)
		payload = resp.json()
		self.assertTrue(any(item['name'] == 'Produto Especial' for item in payload['results']))
		first = payload['results'][0]
		self.assertIn('stock', first)

	def test_lookup_suppliers_returns_document(self):
		Supplier.objects.create(
			name='Fornecedor XPTO',
			person_type=Supplier.PersonType.LEGAL,
			document='12345678000111',
			code='12345678000111',
			email='fornecedor@example.com'
		)
		resp = self.client.get(reverse('core:lookup', args=['suppliers']), {'q': 'XPTO'})
		self.assertEqual(resp.status_code, 200)
		payload = resp.json()
		self.assertTrue(any('XPTO' in item['name'] for item in payload['results']))
		entry = payload['results'][0]
		self.assertIn('document', entry)

	def test_lookup_brands_returns_label(self):
		Brand.objects.create(name='Marca Teste')
		resp = self.client.get(reverse('core:lookup', args=['brands']), {'q': 'Marca'})
		self.assertEqual(resp.status_code, 200)
		payload = resp.json()
		self.assertTrue(any(item['label'] == 'Marca Teste' for item in payload['results']))

	def test_lookup_categories_returns_label(self):
		Category.objects.create(name='Categoria XYZ')
		resp = self.client.get(reverse('core:lookup', args=['categories']), {'q': 'XYZ'})
		self.assertEqual(resp.status_code, 200)
		payload = resp.json()
		self.assertTrue(any(item['label'] == 'Categoria XYZ' for item in payload['results']))

	def test_lookup_departments_returns_label(self):
		Department.objects.create(name='Depart 123')
		resp = self.client.get(reverse('core:lookup', args=['departments']), {'q': '123'})
		self.assertEqual(resp.status_code, 200)
		payload = resp.json()
		self.assertTrue(any(item['label'] == 'Depart 123' for item in payload['results']))

	def test_lookup_volumes_returns_label(self):
		Volume.objects.create(description='Caixa 10L')
		resp = self.client.get(reverse('core:lookup', args=['volumes']), {'q': '10L'})
		self.assertEqual(resp.status_code, 200)
		payload = resp.json()
		self.assertTrue(any(item['label'] == 'Caixa 10L' for item in payload['results']))

	def test_lookup_units_returns_label(self):
		UnitOfMeasure.objects.create(code='CX', name='Caixa')
		resp = self.client.get(reverse('core:lookup', args=['units']), {'q': 'CX'})
		self.assertEqual(resp.status_code, 200)
		payload = resp.json()
		self.assertTrue(any(item['code'] == 'CX' for item in payload['results']))

	def test_lookup_product_groups_returns_label(self):
		group = ProductGroup.objects.create(name='Grupo Teste')
		resp = self.client.get(reverse('core:lookup', args=['product_groups']), {'q': 'Grupo'})
		self.assertEqual(resp.status_code, 200)
		payload = resp.json()
		self.assertTrue(any(item['label'] == str(group) for item in payload['results']))

	def test_lookup_product_subgroups_returns_full_name(self):
		group = ProductGroup.objects.create(name='Linha Principal')
		subgroup = ProductSubGroup.objects.create(group=group, name='Sub Linha')
		resp = self.client.get(reverse('core:lookup', args=['product_subgroups']), {'q': 'Sub'})
		self.assertEqual(resp.status_code, 200)
		payload = resp.json()
		self.assertTrue(any(item['label'] == subgroup.full_name for item in payload['results']))

	def test_lookup_quotes_returns_total(self):
		client = Client.objects.create(
			person_type=Client.PersonType.LEGAL,
			document='12345678000199',
			email='empresa@example.com',
			first_name='Empresa',
			last_name='Alvo',
		)
		quote = Quote.objects.create(client=client)
		QuoteItem.objects.create(
			quote=quote,
			description='Serviço',
			quantity=Decimal('2'),
			unit_price=Decimal('50'),
			discount=Decimal('10'),
		)
		resp = self.client.get(reverse('core:lookup', args=['quotes']), {'q': quote.number})
		self.assertEqual(resp.status_code, 200)
		payload = resp.json()
		self.assertTrue(any(item['number'] == quote.number for item in payload['results']))
		entry = next(item for item in payload['results'] if item['number'] == quote.number)
		self.assertEqual(entry['total'], '90.00')


class DashboardTests(TestCase):
	def test_dashboard_lists_pending_adjustments(self):
		user = User.objects.create_user('dash', 'dash@example.com', 'pw123456')
		self.client.login(username='dash', password='pw123456')
		product = Product.objects.create(name='Produto X', price=Decimal('10.00'))
		batch = PriceAdjustmentBatch.objects.create(
			created_by=user,
			rule_type=PriceAdjustmentBatch.Rule.INCREASE_PERCENT,
			parameters={'percent': '10'},
		)
		item = PriceAdjustmentItem.objects.create(
			batch=batch,
			product=product,
			old_price=Decimal('10.00'),
			new_price=Decimal('11.00'),
		)

		resp = self.client.get(reverse('dashboard'))
		self.assertEqual(resp.status_code, 200)
		self.assertIn(item, list(resp.context['pending_adjustments']))
		self.assertContains(resp, 'Reajustes de preço pendentes')
		self.assertContains(resp, product.name)
		self.assertContains(resp, f'#{batch.pk}')
