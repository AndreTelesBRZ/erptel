from datetime import timedelta
import io
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client as TestClient, TestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import Company
from core.models import UserAccessProfile
from companies.services import SefazAPIError

from .models import (
	Product,
	Supplier,
    ProductGroup,
    ProductSubGroup,
    SupplierProductPrice,
	PriceAdjustmentBatch,
	PriceAdjustmentItem,
	PriceAdjustmentLog,
)


class ProductModelTest(TestCase):
	def test_create_product(self):
		p = Product.objects.create(name='Test', code='SKU123', description='Desc', price='9.99', pricing_base_cost='5.00')
		self.assertEqual(str(p), 'Test (SKU123)')
		p.refresh_from_db()
		self.assertEqual(p.pricing_base_cost, Decimal('5.00'))

	def test_pricing_calculation(self):
		product = Product(name='Prod Calc', code='PCALC', price='0')
		product.pricing_base_cost = Decimal('50')
		product.pricing_variable_expense_percent = Decimal('10')
		product.pricing_fixed_expense_percent = Decimal('5')
		product.pricing_tax_percent = Decimal('12')
		product.pricing_desired_margin_percent = Decimal('15')
		product.calculate_pricing(force=True)
		self.assertEqual(product.pricing_markup_factor, Decimal('1.7241'))
		self.assertEqual(product.pricing_suggested_price, Decimal('86.21'))

	def test_lifecycle_status_based_on_dates(self):
		today = timezone.localdate()
		product = Product.objects.create(
			name='Lifecycle',
			code='LC001',
			price='10.00',
			lifecycle_start_date=today,
		)
		self.assertTrue(product.is_lifecycle_active)

		product.lifecycle_end_date = today
		product.save()
		self.assertFalse(product.is_lifecycle_active)

		product.lifecycle_end_date = today + timedelta(days=1)
		self.assertTrue(product.is_lifecycle_active)


class ProductViewTest(TestCase):
	def test_index_public(self):
		c = TestClient()
		resp = c.get('/products/')
		self.assertEqual(resp.status_code, 200)

	def test_create_requires_login(self):
		c = TestClient()
		resp = c.get('/products/create/')
		self.assertEqual(resp.status_code, 302)

	def test_supplier_requires_login(self):
		c = TestClient()
		resp = c.get(reverse('products:supplier_list'))
		self.assertEqual(resp.status_code, 302)

	def test_supplier_create(self):
		user = User.objects.create_user('user_sup', 'sup@example.com', 'pw123456')
		c = TestClient()
		c.login(username='user_sup', password='pw123456')
		resp = c.post(reverse('products:supplier_list'), {
			'name': 'Fornecedor A',
			'person_type': Supplier.PersonType.LEGAL,
			'document': '12.345.678/0001-90',
		})
		self.assertEqual(resp.status_code, 302)
		self.assertTrue(Supplier.objects.filter(name='Fornecedor A', document='12345678000190', code='12345678000190').exists())

	def test_supplier_sefaz_lookup_requires_login(self):
		resp = TestClient().get(reverse('products:supplier_sefaz_lookup'), {'cnpj': '12345678000190'})
		self.assertEqual(resp.status_code, 302)

	@patch('products.views.fetch_company_data_from_sefaz')
	def test_supplier_sefaz_lookup_success(self, mock_fetch):
		mock_fetch.return_value = {
			'name': 'Fornecedor XYZ',
			'tax_id': '12.345.678/0001-90',
			'email': 'contato@fornecedor.com',
			'phone': '1130303030',
			'city': 'Campinas',
		}
		user = User.objects.create_user('user_sup2', 'sup2@example.com', 'pw123456')
		c = TestClient()
		c.login(username='user_sup2', password='pw123456')
		resp = c.get(reverse('products:supplier_sefaz_lookup'), {'cnpj': '12.345.678/0001-90'})
		self.assertEqual(resp.status_code, 200)
		payload = resp.json()['data']
		self.assertEqual(payload['name'], 'Fornecedor XYZ')
		self.assertEqual(payload['person_type'], Supplier.PersonType.LEGAL)
		self.assertEqual(payload['city'], 'Campinas')
		mock_fetch.assert_called_once()

	@patch('products.views.fetch_company_data_from_sefaz')
	def test_supplier_sefaz_lookup_error(self, mock_fetch):
		mock_fetch.side_effect = SefazAPIError('Falha na SEFAZ')
		user = User.objects.create_user('user_sup3', 'sup3@example.com', 'pw123456')
		c = TestClient()
		c.login(username='user_sup3', password='pw123456')
		resp = c.get(reverse('products:supplier_sefaz_lookup'), {'cnpj': '12345678000190'})
		self.assertEqual(resp.status_code, 502)
		self.assertEqual(resp.json()['error'], 'Falha na SEFAZ')

	def test_export_pdf_requires_selection(self):
		User.objects.create_user('user1', 'user1@example.com', 'pw123456')
		Product.objects.create(name='Prod A', price='5.99')

		c = TestClient()
		c.login(username='user1', password='pw123456')
		resp = c.post(reverse('products:report_pdf'), {'return_url': reverse('products:index')})
		self.assertEqual(resp.status_code, 302)

	def test_export_pdf_with_selection(self):
		User.objects.create_user('user2', 'user2@example.com', 'pw123456')
		product = Product.objects.create(name='Prod B', price='11.50', stock='3')

		c = TestClient()
		c.login(username='user2', password='pw123456')
		resp = c.post(
			reverse('products:report_pdf'),
			{'product_ids': [str(product.pk)], 'return_url': reverse('products:index')}
		)

		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp['Content-Type'], 'application/pdf')
		self.assertGreater(len(resp.content), 200)

	def test_default_index_order_by_reference(self):
		Product.objects.create(name='Prod B', code='SKU2', reference='B002', supplier_code='B900')
		Product.objects.create(name='Prod A', code='SKU1', reference='A001', supplier_code='A900')
		Product.objects.create(name='Prod C', code='SKU3', reference='C010', supplier_code='C900')

		c = TestClient()
		resp = c.get(reverse('products:index'))
		self.assertEqual(resp.status_code, 200)

		products = list(resp.context['products'])
		self.assertGreaterEqual(len(products), 3)
		self.assertEqual(products[0].reference, 'A001')

	def test_reference_sort_falls_back_to_supplier_code(self):
		Product.objects.create(name='Prod X', code='SKU10', supplier_code='ZZZ')
		Product.objects.create(name='Prod Y', code='SKU11', reference='AAA')

		c = TestClient()
		resp = c.get(reverse('products:index'))
		self.assertEqual(resp.status_code, 200)

		products = list(resp.context['products'])
		self.assertEqual(products[0].reference or products[0].supplier_code, 'AAA')

	def test_group_list_requires_login(self):
		resp = TestClient().get(reverse('products:group_list'))
		self.assertEqual(resp.status_code, 302)

	def test_group_create(self):
		user = User.objects.create_user('manager', 'manager@example.com', 'pw123456')
		c = TestClient()
		c.login(username='manager', password='pw123456')
		resp = c.post(reverse('products:group_list'), {'name': 'Eletrônicos'})
		self.assertEqual(resp.status_code, 302)
		self.assertTrue(ProductGroup.objects.filter(name='Eletrônicos').exists())

	def test_subgroup_create_nested(self):
		user = User.objects.create_user('manager2', 'manager2@example.com', 'pw123456')
		c = TestClient()
		c.login(username='manager2', password='pw123456')
		group = ProductGroup.objects.create(name='Ferramentas')
		parent = ProductSubGroup.objects.create(group=group, name='Parafusos')
		resp = c.post(reverse('products:subgroup_list'), {
			'group': str(group.pk),
			'parent_subgroup': str(parent.pk),
			'name': 'Parafusos Allen',
		})
		self.assertEqual(resp.status_code, 302)
		self.assertTrue(ProductSubGroup.objects.filter(name='Parafusos Allen', parent_subgroup=parent, group=group).exists())

	def test_filter_by_company(self):
		company_a = Company.objects.create(name='Empresa A', tax_id='00.000.000/0001-00')
		company_b = Company.objects.create(name='Empresa B', tax_id='00.000.000/0002-99')

		product_a = Product.objects.create(name='Prod Empresa A', code='A01', price='12.00', reference='AAA')
		product_b = Product.objects.create(name='Prod Empresa B', code='B01', price='15.00', reference='BBB')

		product_a.companies.add(company_a)
		product_b.companies.add(company_b)

		c = TestClient()
		resp = c.get(reverse('products:index'), {'company': company_a.id})
		self.assertEqual(resp.status_code, 200)

		products = list(resp.context['products'])
		self.assertIn(product_a, products)
		self.assertNotIn(product_b, products)
		self.assertEqual(resp.context['selected_company_obj'], company_a)


class SupplierCatalogTest(TestCase):
	def setUp(self):
		self.user = User.objects.create_user('catalog', 'catalog@example.com', 'pw123456')
		self.client = TestClient()
		self.client.login(username='catalog', password='pw123456')
		self.supplier = Supplier.objects.create(name='Fornecedor Cat', person_type=Supplier.PersonType.LEGAL, document='12345678000190', code='12345678000190')
		self.company = Company.objects.create(
			code='00000000000377',
			name='Empresa Suprimentos',
			trade_name='Empresa Suprimentos',
			tax_id='00.000.000/0003-77',
		)
		profile, _ = UserAccessProfile.objects.get_or_create(user=self.user)
		profile.companies.add(self.company)
		session = self.client.session
		session['active_company_id'] = self.company.pk
		session.save()

	def test_add_catalog_item(self):
		resp = self.client.post(reverse('products:supplier_catalog', args=[self.supplier.pk]), {
			'action': 'add',
			'code': 'A100',
			'description': 'Produto Catálogo',
			'unit': 'CX',
			'unit_price': '10.50',
			'valid_from': '2024-01-01',
		})
		self.assertEqual(resp.status_code, 302)
		self.assertTrue(SupplierProductPrice.objects.filter(supplier=self.supplier, code='A100').exists())

	def test_import_catalog_csv(self):
		csv_content = '\ufeffCódigo;Descrição;Unidade;Qtd. etiq.;Qtd. por embalagem;Valor unitário;IPI (%);Frete (%);ST (%);Custo reposição;Início vigência;Fim vigência\n'
		csv_content += 'B200;Item CSV;UN;1;1;12,34;6,5;10;38;15,44;2024-02-01;2024-12-31\n'
		file = io.BytesIO(csv_content.encode('utf-8'))
		file.name = 'catalogo.csv'
		resp = self.client.post(reverse('products:supplier_catalog', args=[self.supplier.pk]),
			{'action': 'import', 'file': file}, follow=True)
		self.assertEqual(resp.status_code, 200)
		self.assertTrue(SupplierProductPrice.objects.filter(
			supplier=self.supplier,
			code='B200',
			valid_from=timezone.datetime(2024, 2, 1).date()
		).exists())

	def test_edit_catalog_item(self):
		item = SupplierProductPrice.objects.create(
			supplier=self.supplier,
			code='C300',
			description='Item Edit',
			unit_price=Decimal('5.00'),
			valid_from=timezone.datetime(2024, 1, 1).date(),
		)
		resp = self.client.post(reverse('products:supplier_catalog_edit', args=[self.supplier.pk, item.pk]), {
			'code': 'C300',
			'description': 'Item Editado',
			'unit_price': '6.50',
			'valid_from': '2024-01-01',
			'valid_until': '',
		})
		self.assertEqual(resp.status_code, 302)
		item.refresh_from_db()
		self.assertEqual(item.description, 'Item Editado')
		self.assertEqual(item.unit_price, Decimal('6.50'))

	def test_select_products_creates_entries(self):
		product1 = Product.objects.create(name='Prod Selecionado 1', code='S1', price=Decimal('9.99'))
		product2 = Product.objects.create(name='Prod Selecionado 2', code='S2', price=Decimal('19.99'))
		product1.companies.add(self.company)
		product2.companies.add(self.company)
		resp = self.client.post(reverse('products:supplier_catalog_select', args=[self.supplier.pk]), {
			'product_ids': [str(product1.pk), str(product2.pk)],
			'valid_from': '2024-03-01',
			'valid_until': '',
		})
		self.assertEqual(resp.status_code, 302)
		self.assertTrue(SupplierProductPrice.objects.filter(supplier=self.supplier, code='S1').exists())
		self.assertTrue(SupplierProductPrice.objects.filter(supplier=self.supplier, code='S2').exists())

	def test_bulk_from_selection_view_creates_catalog_items(self):
		product1 = Product.objects.create(name='Prod Bulk 1', code='BULK1', price=Decimal('8.50'))
		product2 = Product.objects.create(name='Prod Bulk 2', code='BULK2', price=Decimal('12.40'))
		product1.companies.add(self.company)
		product2.companies.add(self.company)
		resp = self.client.post(reverse('products:supplier_catalog_from_selection'), {
			'product_ids': [str(product1.pk), str(product2.pk)],
		})
		self.assertEqual(resp.status_code, 200)
		self.assertTemplateUsed(resp, 'products/supplier_catalog_bulk_add.html')

		resp = self.client.post(reverse('products:supplier_catalog_from_selection'), {
			'confirm': '1',
			'selected_ids': [str(product1.pk), str(product2.pk)],
			'supplier': str(self.supplier.pk),
			'valid_from': '2024-05-01',
			'valid_until': '',
		})
		self.assertEqual(resp.status_code, 302)
		self.assertTrue(SupplierProductPrice.objects.filter(supplier=self.supplier, code='BULK1').exists())
		self.assertTrue(SupplierProductPrice.objects.filter(supplier=self.supplier, code='BULK2').exists())


class PriceAdjustmentFlowTest(TestCase):
	def setUp(self):
		self.user = User.objects.create_user('manager', 'manager@example.com', 'pw123456')
		self.client = TestClient()
		self.client.login(username='manager', password='pw123456')

	def _create_batch_with_item(self):
		product = Product.objects.create(
			name='Produto Teste',
			code='P001',
			price=Decimal('10.00'),
			cost_price=Decimal('7.50'),
		)
		batch = PriceAdjustmentBatch.objects.create(
			created_by=self.user,
			rule_type=PriceAdjustmentBatch.Rule.INCREASE_PERCENT,
			parameters={'percent': '10'},
		)
		item = PriceAdjustmentItem.objects.create(
			batch=batch,
			product=product,
			old_price=Decimal('10.00'),
			new_price=Decimal('11.00'),
			cost_value=Decimal('7.50'),
			old_margin_percent=Decimal('25.00'),
			new_margin_percent=Decimal('31.82'),
			rule_snapshot=batch.parameters,
		)
		return batch, item, product

	def test_approve_updates_product_and_batch_status(self):
		batch, item, product = self._create_batch_with_item()

		resp = self.client.post(
			reverse('products:price_adjustment_detail', args=[batch.pk]),
			{f'status_{item.pk}': PriceAdjustmentItem.Status.APPROVED},
		)
		self.assertEqual(resp.status_code, 302)

		product.refresh_from_db()
		item.refresh_from_db()
		batch.refresh_from_db()

		self.assertEqual(product.price, Decimal('11.00'))
		self.assertEqual(item.status, PriceAdjustmentItem.Status.APPROVED)
		self.assertEqual(item.message, 'Preço aprovado.')
		self.assertEqual(batch.status, PriceAdjustmentBatch.Status.APPROVED)
		logs = list(PriceAdjustmentLog.objects.all())
		self.assertEqual(len(logs), 1)
		self.assertEqual(logs[0].old_price, Decimal('10.00'))
		self.assertEqual(logs[0].new_price, Decimal('11.00'))
		self.assertEqual(logs[0].action, PriceAdjustmentItem.Status.APPROVED)

	def test_reject_reverts_price(self):
		batch, item, product = self._create_batch_with_item()

		# First approve to change the product price.
		self.client.post(
			reverse('products:price_adjustment_detail', args=[batch.pk]),
			{f'status_{item.pk}': PriceAdjustmentItem.Status.APPROVED},
		)

		resp = self.client.post(
			reverse('products:price_adjustment_detail', args=[batch.pk]),
			{f'status_{item.pk}': PriceAdjustmentItem.Status.REJECTED},
		)
		self.assertEqual(resp.status_code, 302)

		product.refresh_from_db()
		item.refresh_from_db()
		batch.refresh_from_db()

		self.assertEqual(product.price, Decimal('10.00'))
		self.assertEqual(item.status, PriceAdjustmentItem.Status.REJECTED)
		self.assertEqual(item.message, 'Item rejeitado.')
		self.assertEqual(batch.status, PriceAdjustmentBatch.Status.REJECTED)
		logs = list(PriceAdjustmentLog.objects.order_by('created_at'))
		self.assertEqual(len(logs), 2)
		self.assertEqual(logs[0].action, PriceAdjustmentItem.Status.APPROVED)
		self.assertEqual(logs[1].action, PriceAdjustmentItem.Status.REJECTED)
		self.assertEqual(logs[1].new_price, Decimal('10.00'))

	def test_bulk_apply_selected_items(self):
		batch, item1, product1 = self._create_batch_with_item()
		product2 = Product.objects.create(
			name='Produto Y',
			code='P002',
			price=Decimal('20.00'),
			cost_price=Decimal('16.00'),
		)
		item2 = PriceAdjustmentItem.objects.create(
			batch=batch,
			product=product2,
			old_price=Decimal('20.00'),
			new_price=Decimal('22.00'),
			cost_value=Decimal('16.00'),
			old_margin_percent=Decimal('20.00'),
			new_margin_percent=Decimal('27.27'),
			rule_snapshot=batch.parameters,
		)

		resp = self.client.post(
			reverse('products:price_adjustment_detail', args=[batch.pk]),
			{
				'selected_items': [str(item1.pk), str(item2.pk)],
				'bulk_status': PriceAdjustmentItem.Status.APPROVED,
				'bulk_apply': '1',
			},
		)
		self.assertEqual(resp.status_code, 302)

		product1.refresh_from_db()
		product2.refresh_from_db()
		item1.refresh_from_db()
		item2.refresh_from_db()
		batch.refresh_from_db()

		self.assertEqual(product1.price, Decimal('11.00'))
		self.assertEqual(product2.price, Decimal('22.00'))
		self.assertEqual(item1.status, PriceAdjustmentItem.Status.APPROVED)
		self.assertEqual(item2.status, PriceAdjustmentItem.Status.APPROVED)
		self.assertEqual(batch.status, PriceAdjustmentBatch.Status.APPROVED)
		self.assertEqual(PriceAdjustmentLog.objects.filter(item__in=[item1, item2]).count(), 2)

	def test_history_view_lists_logs(self):
		batch, item, product = self._create_batch_with_item()
		self.client.post(
			reverse('products:price_adjustment_detail', args=[batch.pk]),
			{f'status_{item.pk}': PriceAdjustmentItem.Status.APPROVED},
		)
		resp = self.client.get(reverse('products:price_adjustment_history'))
		self.assertEqual(resp.status_code, 200)
		self.assertContains(resp, product.name)
		self.assertContains(resp, '#{}'.format(batch.pk))

	def test_price_adjustment_preview_displays_comparison(self):
		product = Product.objects.create(
			name='Produto Preview',
			code='PP001',
			price=Decimal('10.00'),
			cost_price=Decimal('7.50'),
		)
		# Initial load with selected ids
		resp = self.client.post(
			reverse('products:price_adjustment_prepare'),
			{'product_ids': [str(product.pk)]},
		)
		self.assertEqual(resp.status_code, 200)
		self.assertFalse(resp.context['preview_ready'])

		resp = self.client.post(
			reverse('products:price_adjustment_prepare'),
			{
				'selected_ids': [str(product.pk)],
				'rule_type': PriceAdjustmentBatch.Rule.INCREASE_PERCENT,
				'percent': '10',
				'preview': '1',
			},
		)
		self.assertEqual(resp.status_code, 200)
		self.assertTrue(resp.context['preview_ready'])
		self.assertContains(resp, 'Novo preço')
		self.assertContains(resp, '11.00')
		self.assertEqual(PriceAdjustmentBatch.objects.count(), 0)

	def test_price_adjustment_requires_preview_before_confirm(self):
		product = Product.objects.create(
			name='Produto Confirm',
			code='PC001',
			price=Decimal('10.00'),
			cost_price=Decimal('7.50'),
		)
		url = reverse('products:price_adjustment_prepare')

		resp = self.client.post(
			url,
			{
				'selected_ids': [str(product.pk)],
				'rule_type': PriceAdjustmentBatch.Rule.INCREASE_PERCENT,
				'percent': '5',
				'confirm': '1',
			},
		)
		self.assertEqual(resp.status_code, 200)
		self.assertTrue(resp.context['preview_ready'])
		self.assertEqual(PriceAdjustmentBatch.objects.count(), 0)

		resp = self.client.post(
			url,
			{
				'selected_ids': [str(product.pk)],
				'rule_type': PriceAdjustmentBatch.Rule.INCREASE_PERCENT,
				'percent': '5',
				'confirm': '1',
				'preview_ready': '1',
			},
		)
		self.assertEqual(resp.status_code, 302)
		batch = PriceAdjustmentBatch.objects.latest('pk')
		item = batch.items.get(product=product)
		self.assertEqual(item.old_price, Decimal('10.00'))
		self.assertEqual(item.new_price, Decimal('10.50'))
