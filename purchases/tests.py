from django.urls import reverse
from django.test import TestCase, Client
from django.contrib.auth.models import User

from .models import PurchaseOrder


class PurchaseViewsTest(TestCase):
	def setUp(self):
		self.client = Client()
		self.user = User.objects.create_user('buyer', 'buyer@example.com', 'pw123456')

	def test_requires_login(self):
		resp = self.client.get(reverse('purchases:index'))
		self.assertEqual(resp.status_code, 302)

	def test_index_lists_orders(self):
		PurchaseOrder.objects.create(order_number='PO-001', supplier='Fornecedor A', status='sent', total_amount=1200)
		self.client.login(username='buyer', password='pw123456')

		resp = self.client.get(reverse('purchases:index'))
		self.assertEqual(resp.status_code, 200)
		self.assertContains(resp, 'PO-001')
