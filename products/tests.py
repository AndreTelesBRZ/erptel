from django.test import TestCase, Client as TestClient
from .models import Product


class ProductModelTest(TestCase):
	def test_create_product(self):
		p = Product.objects.create(name='Test', description='Desc', price='9.99')
		self.assertEqual(str(p), 'Test - 9.99')


class ProductViewTest(TestCase):
	def test_index_public(self):
		c = TestClient()
		resp = c.get('/products/')
		self.assertEqual(resp.status_code, 200)

	def test_create_requires_login(self):
		c = TestClient()
		resp = c.get('/products/create/')
		self.assertEqual(resp.status_code, 302)
