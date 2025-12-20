from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from clients.models import Client
from companies.models import Company
from core.models import UserAccessProfile
from products.models import Product, ProductStock
from .models import Quote, QuoteItem, Order, OrderItem, Salesperson


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
		self.assertEqual(response.status_code, 302)
		order = Order.objects.first()
		self.assertIsNotNone(order)
		self.assertTrue(order.number.startswith('PD'))
		self.assertEqual(order.total_amount, Decimal('9.50'))
		self.assertEqual(order.company, self.company)

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
