from django.test import TestCase, Client as TestClient
from .models import Client as ClientModel


class ClientModelTest(TestCase):
	def test_create_client(self):
		c = ClientModel.objects.create(first_name='A', last_name='B', email='a@b.com')
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
