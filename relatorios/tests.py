from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from clients.models import Client
from companies.models import Company
from core.models import UserAccessProfile
from products.models import Product, ProductStock
from purchases.models import PurchaseOrder
from sales.models import Order, OrderItem, Quote, QuoteItem

from .services import get_report_context


def create_sample_data():
    loja_codigo = "00003"
    company = Company.objects.create(
        code="00000000000123",
        name="Empresa Matriz",
        tax_id="00.000.000/0001-23",
        trade_name="Empresa Matriz",
    )
    client = Client.objects.create(
        person_type=Client.PersonType.INDIVIDUAL,
        code="11122233344",
        document="11122233344",
        first_name="Cliente",
        last_name="Teste",
        email="cliente@example.com",
    )

    product = Product.objects.create(
        name="Produto Teste",
        price=Decimal("100.00"),
        stock=Decimal("0.00"),
        min_stock=Decimal("10"),
    )
    product.companies.add(company)
    ProductStock.objects.create(product=product, company=company, quantity=Decimal("5"), min_quantity=Decimal("10"))

    quote_approved = Quote.objects.create(
        client=client,
        status=Quote.Status.APPROVED,
        company=company,
        loja_codigo=loja_codigo,
    )
    QuoteItem.objects.create(
        quote=quote_approved,
        quantity=1,
        unit_price=Decimal("200.00"),
        loja_codigo=loja_codigo,
    )

    quote_converted = Quote.objects.create(
        client=client,
        status=Quote.Status.CONVERTED,
        company=company,
        loja_codigo=loja_codigo,
    )
    QuoteItem.objects.create(
        quote=quote_converted,
        quantity=1,
        unit_price=Decimal("150.00"),
        loja_codigo=loja_codigo,
    )

    order = Order.objects.create(
        client=client,
        status=Order.Status.CONFIRMED,
        issue_date=timezone.localdate(),
        company=company,
        loja_codigo=loja_codigo,
    )
    OrderItem.objects.create(
        order=order,
        quantity=2,
        unit_price=Decimal("150.00"),
        loja_codigo=loja_codigo,
    )

    PurchaseOrder.objects.create(
        order_number="PO-001",
        supplier="Fornecedor Teste",
        total_amount=Decimal("500.00"),
        status="received",
        company=company,
    )

    return company


class ReportServicesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = create_sample_data()

    def test_get_report_context_returns_expected_metrics(self):
        context = get_report_context(company=self.company, loja_codigo="00003")

        sales_summary = context["sales_report"]["summary"]
        purchase_summary = context["purchase_report"]["summary"]
        product_summary = context["product_report"]["summary"]

        self.assertEqual(sales_summary["total_orders"], 1)
        self.assertEqual(sales_summary["total_order_value"], Decimal("300.00"))
        self.assertEqual(sales_summary["total_quotes"], 2)
        self.assertEqual(sales_summary["total_quote_value"], Decimal("350.00"))
        self.assertEqual(sales_summary["conversion_rate"], Decimal("100.00"))

        self.assertEqual(purchase_summary["total_orders"], 1)
        self.assertEqual(purchase_summary["total_amount"], Decimal("500.00"))

        self.assertEqual(product_summary["total_products"], 1)
        self.assertEqual(product_summary["inventory_value"], Decimal("500.00"))
        self.assertEqual(product_summary["average_price"], Decimal("100.00"))

        stock_info = context["product_report"]["stock"]
        self.assertEqual(stock_info["low_stock"], 1)
        self.assertEqual(stock_info["out_of_stock"], 0)


class ReportViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="analista",
            email="analista@example.com",
            password="senha-muito-segura",
        )
        cls.company = create_sample_data()
        profile, _ = UserAccessProfile.objects.get_or_create(user=cls.user)
        profile.companies.add(cls.company)

    def test_index_requires_authentication(self):
        response = self.client.get(reverse("relatorios:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_index_displays_report_context(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['active_company_id'] = self.company.pk
        session.save()
        response = self.client.get(reverse("relatorios:index"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "relatorios/index.html")
        self.assertIn("sales_report", response.context)
        self.assertEqual(response.context["sales_report"]["summary"]["total_orders"], 1)
