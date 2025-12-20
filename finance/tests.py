from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from .models import FinanceEntry


class FinanceViewsTest(TestCase):
	def setUp(self):
		self.client = Client()
		self.user = User.objects.create_user('finance', 'finance@example.com', 'pw123456')

	def test_requires_login(self):
		resp = self.client.get(reverse('finance:index'))
		self.assertEqual(resp.status_code, 302)

	def test_index_lists_entries(self):
		FinanceEntry.objects.create(title='Mensalidade', entry_type='receivable', amount=500)
		self.client.login(username='finance', password='pw123456')
		resp = self.client.get(reverse('finance:index'))
		self.assertEqual(resp.status_code, 200)
		self.assertContains(resp, 'Mensalidade')
