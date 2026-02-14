from decimal import Decimal
from django.utils import timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from clients.models import Client
from companies.models import Company
from core.models import UserAccessProfile
from products.models import Product, ProductStock
from .models import ItemPedido, Pedido, Quote, QuoteItem, Order, OrderItem, Salesperson


class SalesTestCase(TestCase):
	def setUp(self):
		self.user = User.objects.create_user('sales', 'sales@example.com', 'pw123456')
		self.client_user = Client.objects.create(person_type='F', document='12345678901', first_name='Ana', last_name='Silva', email='ana@example.com')
		self.company = Company.objects.create(
			code='00000000000466',
			name='Empresa Vendas',
			trade_name='Empresa Vendas',
			tax_id='00.000.000/0004-66',
		)
		profile, _ = UserAccessProfile.objects.get_or_create(user=self.user)
		profile.companies.add(self.company)
		self.product = Product.objects.create(name='Produto X', code='PX', price=Decimal('10.00'), stock=Decimal('0.00'))
		self.product.companies.add(self.company)
		ProductStock.objects.create(product=self.product, company=self.company, quantity=Decimal('10.00'))

	def login(self):
		self.client.login(username='sales', password='pw123456')
		session = self.client.session
		session['active_company_id'] = self.company.pk
		session.save()

	def test_quote_number_and_total(self):
		quote = Quote.objects.create(client=self.client_user, company=self.company)
		QuoteItem.objects.create(
			quote=quote,
			product=self.product,
			description='Produto X',
			quantity=Decimal('2'),
			unit_price=Decimal('15.00'),
			discount=Decimal('5.00'),
		)
		self.assertTrue(quote.number.startswith('OR'))
		self.assertEqual(quote.total_amount, Decimal('25.00'))

	def test_quote_create_view(self):
		self.login()
		url = reverse('sales:quote_create')
		salesperson = Salesperson.objects.create(
			user=self.user,
			cpf='12345678902',
			code='12345678902',
			is_active=True,
		)
		response = self.client.post(url, {
			'client': str(self.client_user.pk),
			'valid_until': '2030-01-01',
			'salesperson': str(salesperson.pk),
			'status': Quote.Status.DRAFT,
			'notes': 'Teste de orçamento',
			'items-TOTAL_FORMS': '1',
			'items-INITIAL_FORMS': '0',
			'items-MIN_NUM_FORMS': '1',
			'items-MAX_NUM_FORMS': '1000',
			'items-0-product': str(self.product.pk),
			'items-0-description': '',
			'items-0-quantity': '3',
			'items-0-unit_price': '10.00',
			'items-0-discount': '0',
			'items-0-delivery_days': '',
			'items-0-sort_order': '0',
		})
		self.assertEqual(response.status_code, 302)
		quote = Quote.objects.first()
		self.assertIsNotNone(quote)
		self.assertEqual(quote.items.count(), 1)
		self.assertEqual(quote.total_amount, Decimal('30.00'))
		self.assertEqual(quote.salesperson, salesperson)

	def test_quote_convert_to_order(self):
		self.login()
		quote = Quote.objects.create(client=self.client_user, status=Quote.Status.SENT, company=self.company)
		QuoteItem.objects.create(
			quote=quote,
			product=self.product,
			description='Produto X',
			quantity=Decimal('2'),
			unit_price=Decimal('12.00'),
			discount=Decimal('0.00'),
		)
		url = reverse('sales:quote_convert', args=[quote.pk])
		response = self.client.post(url)
		self.assertEqual(response.status_code, 302)
		order = Order.objects.get(quote=quote)
		self.assertEqual(order.items.count(), 1)
		self.assertEqual(order.total_amount, Decimal('24.00'))
		self.assertEqual(order.company, self.company)
		quote.refresh_from_db()
		self.assertEqual(quote.status, Quote.Status.CONVERTED)

	def test_order_create_view(self):
		self.login()
		url = reverse('sales:order_create')
		count_before = Order.objects.count()
		response = self.client.post(url, {
			'client': str(self.client_user.pk),
			'quote': '',
			'issue_date': '2030-01-01',
			'status': Order.Status.DRAFT,
			'payment_terms': '30 dias',
			'notes': 'Pedido teste',
			'items-TOTAL_FORMS': '1',
			'items-INITIAL_FORMS': '0',
			'items-MIN_NUM_FORMS': '1',
			'items-MAX_NUM_FORMS': '1000',
			'items-0-product': str(self.product.pk),
			'items-0-description': 'Produto X',
			'items-0-quantity': '1',
			'items-0-unit_price': '9.50',
			'items-0-discount': '0',
			'items-0-sort_order': '0',
		})
		self.assertEqual(response.status_code, 403)
		self.assertEqual(Order.objects.count(), count_before)

	def test_order_cancel_sets_status(self):
		self.login()
		order = Order.objects.create(
			client=self.client_user,
			company=self.company,
			issue_date=timezone.localdate(),
			status=Order.Status.CONFIRMED,
		)
		response = self.client.post(reverse('sales:order_cancel', args=[order.pk]))
		self.assertRedirects(response, reverse('sales:order_list'))
		order.refresh_from_db()
		self.assertEqual(order.status, Order.Status.CANCELLED)

	def test_order_invoice_sets_status(self):
		self.login()
		order = Order.objects.create(
			client=self.client_user,
			company=self.company,
			issue_date=timezone.localdate(),
			status=Order.Status.CONFIRMED,
		)
		response = self.client.post(reverse('sales:order_invoice', args=[order.pk]))
		self.assertRedirects(response, reverse('sales:order_list'))
		order.refresh_from_db()
		self.assertEqual(order.status, Order.Status.INVOICED)

	def test_order_set_status_updates_status(self):
		self.login()
		order = Order.objects.create(
			client=self.client_user,
			company=self.company,
			issue_date=timezone.localdate(),
			status=Order.Status.DRAFT,
		)
		response = self.client.post(
			reverse('sales:order_set_status', args=[order.pk]),
			{'status': Order.Status.CONFIRMED},
		)
		self.assertRedirects(response, reverse('sales:order_detail', args=[order.pk]))
		order.refresh_from_db()
		self.assertEqual(order.status, Order.Status.CONFIRMED)

	def test_order_set_status_invalid_choice(self):
		self.login()
		order = Order.objects.create(
			client=self.client_user,
			company=self.company,
			issue_date=timezone.localdate(),
			status=Order.Status.DRAFT,
		)
		response = self.client.post(
			reverse('sales:order_set_status', args=[order.pk]),
			{'status': 'invalid'},
		)
		self.assertRedirects(response, reverse('sales:order_detail', args=[order.pk]))
		order.refresh_from_db()
		self.assertEqual(order.status, Order.Status.DRAFT)

	def test_api_order_pdf(self):
		self.login()
		order = Pedido.objects.create(
			cliente=self.client_user,
			data_criacao=timezone.now(),
			total=Decimal('50.00'),
		)
		ItemPedido.objects.create(
			pedido=order,
			produto=self.product,
			quantidade=Decimal('2'),
			valor_unitario=Decimal('25.00'),
		)
		url = reverse('sales:api_order_pdf', args=[order.pk])
		response = self.client.get(url)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response['Content-Type'], 'application/pdf')
		self.assertIn('inline; filename="pedido-', response['Content-Disposition'])
		self.assertTrue(response.content.startswith(b'%PDF'))

	def test_resolves_vendor_code_from_salesperson_if_missing(self):
		vendor_user = User.objects.create_user('tiago', 'tiago@example.com', 'secret')
		vendor_user.first_name = 'Tiago'
		vendor_user.last_name = 'Oliveira'
		vendor_user.save()
		salesperson = Salesperson.objects.create(
			user=vendor_user,
			cpf='11122233344',
			code='11122233344',
			is_active=True,
		)
		pedido = Pedido.objects.create(
			cliente=self.client_user,
			data_criacao=timezone.now(),
			total=Decimal('20.00'),
			vendedor_nome='Tiago Oliveira',
		)
		self.assertEqual(pedido.resolved_vendedor_codigo, salesperson.code)

	def test_seller_requires_login(self):
		response = self.client.get(reverse('sales:seller_list'))
		self.assertEqual(response.status_code, 302)

	def test_seller_create(self):
		self.login()
		response = self.client.post(reverse('sales:seller_list'), {
			'user': self.user.pk,
			'cpf': '98765432100',
			'phone': '1199999-0000',
			'is_active': 'on',
		})
		self.assertEqual(response.status_code, 302)
		self.assertTrue(Salesperson.objects.filter(user=self.user).exists())

	def test_api_order_detail_is_read_only_ui(self):
		self.login()
		order = Pedido.objects.create(
			cliente=self.client_user,
			data_criacao=timezone.now(),
			total=Decimal('50.00'),
		)
		ItemPedido.objects.create(
			pedido=order,
			produto=self.product,
			quantidade=Decimal('2'),
			valor_unitario=Decimal('25.00'),
		)
		response = self.client.get(reverse('sales:api_order_detail', args=[order.pk]))
		self.assertEqual(response.status_code, 200)
		html = response.content.decode('utf-8')
		self.assertNotIn('Editar Pedido', html)
		self.assertNotIn('Salvar Alterações', html)
		self.assertIn('somente leitura', html.lower())

	def test_api_order_update_endpoint_returns_405(self):
		self.login()
		order = Pedido.objects.create(
			cliente=self.client_user,
			data_criacao=timezone.now(),
			total=Decimal('10.00'),
		)
		response = self.client.generic(
			'PATCH',
			reverse('sales:api_order_update', args=[order.pk]),
			data='{"status":"pre_venda"}',
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 405)

	def test_api_order_item_update_endpoint_returns_405(self):
		self.login()
		order = Pedido.objects.create(
			cliente=self.client_user,
			data_criacao=timezone.now(),
			total=Decimal('10.00'),
		)
		item = ItemPedido.objects.create(
			pedido=order,
			produto=self.product,
			quantidade=Decimal('1'),
			valor_unitario=Decimal('10.00'),
		)
		response = self.client.generic(
			'PATCH',
			reverse('sales:api_order_item_update', args=[order.pk, item.pk]),
			data='{"quantidade":"2"}',
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 405)
