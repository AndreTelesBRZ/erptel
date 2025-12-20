from decimal import Decimal
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import Company
from core.middleware import ActiveCompanyMiddleware
from products.models import Product, Supplier, SupplierProductPrice
from .models import CostBatch, CostBatchItem
from .views import _calc_components


class BatchSelectItemsViewTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		User = get_user_model()
		cls.user = User.objects.create_user(
			username='staff',
			email='staff@example.com',
			password='testpass123',
			is_staff=True,
		)
		cls.batch = CostBatch.objects.create(
			name='Lote teste',
			default_ipi_percent=Decimal('5.0'),
			default_freight_percent=Decimal('2.5'),
		)
		cls.supplier = Supplier.objects.create(
			name='Fornecedor Teste',
			person_type=Supplier.PersonType.LEGAL,
			document='12345678000100',
			code='12345678000100',
		)
		SupplierProductPrice.objects.create(
			supplier=cls.supplier,
			code='FOO123',
			description='Produto Foo',
			unit_price=Decimal('10.00'),
			valid_from=date(2024, 1, 1),
		)
		SupplierProductPrice.objects.create(
			supplier=cls.supplier,
			code='BAR999',
			description='Item Bar',
			unit_price=Decimal('15.00'),
			valid_from=date(2024, 1, 1),
		)

	def test_search_query_filters_items(self):
		self.client.force_login(self.user)
		url = reverse('custos:batch_select_items', args=[self.batch.pk])
		response = self.client.get(url, {'q': 'foo'})

		self.assertEqual(response.status_code, 200)
		items = list(response.context['items'])
		self.assertEqual(len(items), 1)
		self.assertEqual(items[0].code, 'FOO123')
		self.assertEqual(response.context['total'], 1)


class PurchaseCostsUpdateTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		User = get_user_model()
		cls.user = User.objects.create_user(
			username='costs',
			email='costs@example.com',
			password='strongpass',
			is_staff=True,
		)
		cls.company = Company.objects.create(
			code='12345678000100',
			name='Loja Matriz',
			trade_name='Matriz',
			tax_id='12.345.678/0001-00',
		)
		cls.supplier = Supplier.objects.create(
			name='Fornecedor Central',
			person_type=Supplier.PersonType.LEGAL,
			document='10293847560123',
			code='10293847560123',
		)
		cls.product = Product.objects.create(
			name='Parafuso Teste',
			code='PTEST',
			price=Decimal('10.00'),
			cost_price=Decimal('8.00'),
		)
		cls.product.companies.add(cls.company)
		cls.catalog_item = SupplierProductPrice.objects.create(
			supplier=cls.supplier,
			product=cls.product,
			code='PT-001',
			description='Parafuso referência',
			unit_price=Decimal('9.00'),
			ipi_percent=Decimal('5.00'),
			freight_percent=Decimal('3.00'),
			valid_from=date(2024, 1, 1),
		)

	def setUp(self):
		self.client.force_login(self.user)

	def test_updates_product_cost_and_metadata(self):
		url = reverse('custos:purchase_costs')
		data = {
			'form-TOTAL_FORMS': '1',
			'form-INITIAL_FORMS': '1',
			'form-MIN_NUM_FORMS': '0',
			'form-MAX_NUM_FORMS': '1000',
			'form-0-id': str(self.catalog_item.pk),
			'form-0-unit_price': '12.50',
			'form-0-ipi_percent': '4.00',
			'form-0-freight_percent': '2.50',
			'update_products': '1',
		}
		resp = self.client.post(url, data)
		self.assertEqual(resp.status_code, 302)

		self.product.refresh_from_db()
		components = _calc_components(Decimal('12.50'), Decimal('4.00'), Decimal('2.50'))
		self.assertEqual(self.product.cost_price, components['replacement_cost'])
		self.assertIsNotNone(self.product.cost_price_updated_at)
		self.assertIsNotNone(self.product.cost_price_company)
		self.assertEqual(self.product.cost_price_company.pk, self.company.pk)
		self.assertLessEqual(
			abs(timezone.now() - self.product.cost_price_updated_at),
			timedelta(seconds=5)
		)


class BatchDetailSaveTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		User = get_user_model()
		cls.user = User.objects.create_user(
			username='batch-staff',
			email='batch@example.com',
			password='strongpass',
			is_staff=True,
		)
		cls.company = Company.objects.create(
			code='55443322000199',
			name='Filial Teste',
			trade_name='Filial',
			tax_id='55.443.322/0001-99',
		)
		cls.supplier = Supplier.objects.create(
			name='Fornecedor Batch',
			person_type=Supplier.PersonType.LEGAL,
			document='55443322000111',
			code='55443322000111',
		)
		cls.product = Product.objects.create(
			name='Arruela Batch',
			code='ARR-BT',
			price=Decimal('5.00'),
		)
		cls.catalog_item = SupplierProductPrice.objects.create(
			supplier=cls.supplier,
			product=cls.product,
			code='ARR-01',
			description='Arruela zincada',
			unit_price=Decimal('7.00'),
			ipi_percent=Decimal('5.00'),
			freight_percent=Decimal('2.00'),
			valid_from=date(2024, 1, 1),
		)
		cls.batch = CostBatch.objects.create(
			name='Lote conferência',
			default_ipi_percent=Decimal('5.00'),
			default_freight_percent=Decimal('2.00'),
			st_multiplier=Decimal('1.35'),
			st_percent=Decimal('24.00'),
		)
		cls.batch_item = CostBatchItem.objects.create(
			batch=cls.batch,
			supplier_item=cls.catalog_item,
			code=cls.catalog_item.code,
			description=cls.catalog_item.description,
			unit='UN',
			unit_price=Decimal('7.00'),
			ipi_percent=Decimal('5.00'),
			freight_percent=Decimal('2.00'),
		)

	def setUp(self):
		self.client.force_login(self.user)
		session = self.client.session
		session[ActiveCompanyMiddleware.session_key] = self.company.pk
		session.save()

	def test_confirm_updates_supplier_and_product(self):
		url = reverse('custos:batch_detail', args=[self.batch.pk])
		data = {
			'items-TOTAL_FORMS': '1',
			'items-INITIAL_FORMS': '1',
			'items-MIN_NUM_FORMS': '0',
			'items-MAX_NUM_FORMS': '1000',
			'items-0-id': str(self.batch_item.pk),
			'items-0-unit_price': '12.00',
			'items-0-ipi_percent': '4.50',
			'items-0-freight_percent': '1.50',
			'save_items': '1',
		}
		response = self.client.post(url, data)
		self.assertEqual(response.status_code, 302)

		self.catalog_item.refresh_from_db()
		self.product.refresh_from_db()
		expected = self.batch.compute_components(
			unit_price=Decimal('12.00'),
			ipi_percent=Decimal('4.50'),
			freight_percent=Decimal('1.50'),
		)

		self.assertEqual(self.catalog_item.unit_price, Decimal('12.00'))
		self.assertEqual(self.catalog_item.ipi_percent, Decimal('4.50'))
		self.assertEqual(self.catalog_item.freight_percent, Decimal('1.50'))
		self.assertEqual(self.catalog_item.replacement_cost, expected['replacement_cost'])
		self.assertEqual(self.catalog_item.st_percent, self.batch.st_percent)

		self.assertEqual(self.product.cost_price, expected['replacement_cost'])
		self.assertEqual(self.product.cost_price_company.pk, self.company.pk)
		self.assertIsNotNone(self.product.cost_price_updated_at)
