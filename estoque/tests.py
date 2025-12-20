from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch
from companies.models import Company
from core.models import UserAccessProfile
from products.models import Product, ProductStock

from .models import CollectorInventoryItem, Inventory, ZERO_DECIMAL
from .views import INVENTORY_EXPORT_HEADERS


class InventoryModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="estoquista",
            email="estoquista@example.com",
            password="senha-segura",
        )
        cls.company = Company.objects.create(
            code="00000000000199",
            name="Empresa Inventário",
            trade_name="Empresa Inventário",
            tax_id="00.000.000/0001-99",
        )
        cls.product_a = Product.objects.create(
            name="Produto A",
            price=Decimal("10.00"),
            stock=Decimal("0.00"),
            min_stock=Decimal("10.00"),
        )
        cls.product_b = Product.objects.create(
            name="Produto B",
            price=Decimal("20.00"),
            stock=None,
        )
        cls.product_a.companies.add(cls.company)
        cls.product_b.companies.add(cls.company)
        ProductStock.objects.create(product=cls.product_a, company=cls.company, quantity=Decimal("5.00"), min_quantity=Decimal("10.00"))
        ProductStock.objects.create(product=cls.product_b, company=cls.company, quantity=ZERO_DECIMAL)

    def test_start_inventory_freezes_current_stock(self):
        inventory = Inventory.objects.create(name="Inventário Teste", created_by=self.user, company=self.company)
        inventory.start_inventory(self.user)

        inventory.refresh_from_db()
        self.assertEqual(inventory.status, Inventory.Status.IN_PROGRESS)
        self.assertEqual(inventory.items.count(), 2)

        item_a = inventory.items.get(product=self.product_a)
        item_b = inventory.items.get(product=self.product_b)

        self.assertEqual(item_a.frozen_quantity, Decimal("5.00"))
        self.assertEqual(item_b.frozen_quantity, ZERO_DECIMAL)

    def test_close_inventory_updates_product_stock(self):
        inventory = Inventory.objects.create(name="Inventário Ajuste", created_by=self.user, company=self.company)
        inventory.start_inventory(self.user)

        item_a = inventory.items.get(product=self.product_a)
        item_a.counted_quantity = Decimal("7.00")
        item_a.save()

        inventory.close_inventory(self.user)
        inventory.refresh_from_db()
        self.product_a.refresh_from_db()
        self.product_b.refresh_from_db()
        item_a.refresh_from_db()

        self.assertEqual(inventory.status, Inventory.Status.CLOSED)
        self.assertEqual(self.product_a.stock_for_company(self.company), Decimal("7.00"))
        self.assertEqual(self.product_b.stock_for_company(self.company), ZERO_DECIMAL)
        self.assertEqual(item_a.final_quantity, Decimal("7.00"))

    def test_effective_quantity_uses_recount_before_final(self):
        inventory = Inventory.objects.create(name="Inventário Recontagem", created_by=self.user, company=self.company)
        inventory.start_inventory(self.user)
        item = inventory.items.get(product=self.product_a)
        item.counted_quantity = Decimal("6.00")
        item.recount_quantity = Decimal("6.50")
        item.save(update_fields=["counted_quantity", "recount_quantity"])

        self.assertEqual(item.effective_quantity, Decimal("6.50"))

        inventory.close_inventory(self.user)
        item.refresh_from_db()
        self.assertEqual(item.final_quantity, Decimal("6.50"))
        self.assertEqual(self.product_a.stock_for_company(self.company), Decimal("6.50"))

    def test_close_inventory_preserves_manual_final_quantity(self):
        inventory = Inventory.objects.create(name="Inventário Final Manual", created_by=self.user, company=self.company)
        inventory.start_inventory(self.user)
        item = inventory.items.get(product=self.product_a)
        item.final_quantity = Decimal("9.00")
        item.save(update_fields=["final_quantity"])

        inventory.close_inventory(self.user)
        inventory.refresh_from_db()
        item.refresh_from_db()
        self.product_a.refresh_from_db()

        self.assertEqual(inventory.status, Inventory.Status.CLOSED)
        self.assertEqual(item.final_quantity, Decimal("9.00"))
        self.assertEqual(self.product_a.stock_for_company(self.company), Decimal("9.00"))

    def test_inventory_filters_limit_products(self):
        inventory = Inventory.objects.create(
            name="Inventário Filtrado",
            created_by=self.user,
            company=self.company,
            filter_in_stock_only=True,
            filter_query="Produto A",
        )
        # Produto A tem estoque 5, Produto B não possui estoque (None)
        inventory.start_inventory(self.user)

        items = inventory.items.all()
        self.assertEqual(items.count(), 1)
        self.assertEqual(items.first().product, self.product_a)


class InventoryViewsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="gestor",
            email="gestor@example.com",
            password="senha-segura",
        )
        self.company = Company.objects.create(
            code="00000000000288",
            name="Empresa Operações",
            trade_name="Empresa Operações",
            tax_id="00.000.000/0002-88",
        )
        profile, _ = UserAccessProfile.objects.get_or_create(user=self.user)
        profile.companies.add(self.company)
        self.product = Product.objects.create(
            name="Produto Lista",
            price=Decimal("15.00"),
            stock=Decimal("0.00"),
        )
        self.product.companies.add(self.company)
        ProductStock.objects.create(product=self.product, company=self.company, quantity=Decimal("3.00"))
        self.inventory = Inventory.objects.create(name="Inventário View", created_by=self.user, company=self.company)
        session = self.client.session
        session['active_company_id'] = self.company.pk
        session.save()

    def test_list_requires_login(self):
        response = self.client.get(reverse("estoque:inventory_list"))
        self.assertEqual(response.status_code, 302)

    def test_start_inventory_via_view(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("estoque:inventory_start", args=[self.inventory.pk]))
        self.assertEqual(response.status_code, 302)
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.status, Inventory.Status.IN_PROGRESS)
        self.assertEqual(self.inventory.items.count(), 1)

    def test_update_filters_before_start(self):
        self.client.force_login(self.user)
        post_data = {
            "action": "update_filters",
            "name": self.inventory.name,
            "filter_query": "Lista",
            "filter_in_stock_only": "on",
            "filter_below_min_stock": "",
            "filter_group": "",
            "filter_subgroup": "",
            "notes": "",
        }
        response = self.client.post(reverse("estoque:inventory_detail", args=[self.inventory.pk]), data=post_data)
        self.assertEqual(response.status_code, 302)
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.filter_query, "Lista")
        self.assertTrue(self.inventory.filter_in_stock_only)

    def test_create_inventory_from_selection_flow(self):
        self.client.force_login(self.user)
        other_product = Product.objects.create(
            name="Produto Extra",
            code="EXTRA",
            price=Decimal("20.00"),
            stock=Decimal("0.00"),
        )
        other_product.companies.add(self.company)
        ProductStock.objects.create(product=other_product, company=self.company, quantity=Decimal("7.00"))
        resp = self.client.post(reverse("estoque:inventory_from_selection"), {
            "product_ids": [str(self.product.pk), str(other_product.pk)],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "estoque/inventory_prepare.html")

        resp = self.client.post(reverse("estoque:inventory_from_selection"), {
            "confirm": "1",
            "selected_ids": [str(self.product.pk), str(other_product.pk)],
            "name": "Inventário Seleção",
            "notes": "Gerado via seleção",
        })
        self.assertEqual(resp.status_code, 302)
        inventory = Inventory.objects.latest("pk")
        self.assertEqual(inventory.status, Inventory.Status.DRAFT)
        self.assertEqual(inventory.selected_products.count(), 2)
        self.assertEqual(list(inventory.selected_products.order_by("pk")), [self.product, other_product])

    def test_preview_products_matches_filters(self):
        self.inventory.filter_query = "Lista"
        self.inventory.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse("estoque:inventory_detail", args=[self.inventory.pk]))
        self.assertEqual(response.status_code, 200)
        preview = response.context["preview_products"]
        self.assertEqual(len(preview), 1)
        self.assertEqual(preview[0]["product"], self.product)

    def test_update_counts_and_close(self):
        self.client.force_login(self.user)
        self.inventory.start_inventory(self.user)
        item = self.inventory.items.get(product=self.product)

        post_data = {
            "action": "update_counts",
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-id": str(item.pk),
            "form-0-counted_quantity": "4.50",
            "form-0-recount_quantity": "",
        }
        response = self.client.post(reverse("estoque:inventory_detail", args=[self.inventory.pk]), data=post_data)
        self.assertEqual(response.status_code, 302)

        item.refresh_from_db()
        self.assertEqual(item.counted_quantity, Decimal("4.50"))

        response = self.client.post(reverse("estoque:inventory_close", args=[self.inventory.pk]))
        self.assertEqual(response.status_code, 302)
        self.inventory.refresh_from_db()
        self.product.refresh_from_db()

        self.assertEqual(self.inventory.status, Inventory.Status.CLOSED)
        self.assertEqual(self.product.stock_for_company(self.company), Decimal("4.50"))

    def test_export_inventory_csv(self):
        self.client.force_login(self.user)
        self.inventory.start_inventory(self.user)
        item = self.inventory.items.get(product=self.product)

        response = self.client.get(reverse("estoque:inventory_export", args=[self.inventory.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")

        content = response.content.decode("utf-8")
        self.assertIn("Item ID", content)
        self.assertIn(str(item.pk), content)
        self.assertIn(self.inventory.name, content)

    def test_import_inventory_from_csv_and_close(self):
        self.client.force_login(self.user)
        self.inventory.start_inventory(self.user)
        item = self.inventory.items.get(product=self.product)

        csv_header = ";".join(INVENTORY_EXPORT_HEADERS)
        csv_line = ";".join(
            [
                str(self.inventory.pk),
                self.inventory.name,
                self.company.trade_name,
                str(item.pk),
                str(self.product.pk),
                self.product.code or "",
                self.product.name,
                "",
                "3",
                "5",
                "6",
                "7",
            ]
        )
        csv_content = "\ufeffsep=;\n" + csv_header + "\n" + csv_line + "\n"
        upload = SimpleUploadedFile("inventario.csv", csv_content.encode("utf-8"), content_type="text/csv")

        response = self.client.post(
            reverse("estoque:inventory_import", args=[self.inventory.pk]),
            {
                "close_inventory": "on",
                "csv_file": upload,
            },
        )
        self.assertEqual(response.status_code, 302)

        self.inventory.refresh_from_db()
        item.refresh_from_db()
        self.product.refresh_from_db()

        self.assertEqual(self.inventory.status, Inventory.Status.CLOSED)
        self.assertEqual(item.counted_quantity, Decimal("5"))
        self.assertEqual(item.recount_quantity, Decimal("6"))
        self.assertEqual(item.final_quantity, Decimal("7"))
        self.assertEqual(self.product.stock_for_company(self.company), Decimal("7"))


class CollectorInventoryViewsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="coletor",
            email="coletor@example.com",
            password="senha-segura",
        )
        self.client.force_login(self.user)

    @patch("estoque.views._load_plu_mapping", return_value={})
    def test_import_and_update_collector_items(self, mocked_mapping):
        CollectorInventoryItem.objects.all().delete()
        product = Product.objects.create(
            name="Soquete 1/2 SATA 9/16",
            code="14267",
            plu_code="14267",
            price=Decimal("0"),
        )
        content = "0000000014267 ;PARAF SEXT;000001;01;000000000123456\n"
        upload = SimpleUploadedFile("coletor.txt", content.encode("utf-8"), content_type="text/plain")

        response = self.client.post(
            reverse("estoque:inventory_collector"),
            {"action": "import", "arquivo": upload},
        )
        self.assertEqual(response.status_code, 302)

        item = CollectorInventoryItem.objects.get()
        self.assertEqual(item.codigo_produto, "0000000014267")
        self.assertEqual(item.loja, "000001")
        self.assertEqual(item.local, "01")
        self.assertEqual(item.product, product)
        self.assertEqual(item.descricao, "PARAF SEXT")
        self.assertEqual(item.plu_code, "14267")
        product.refresh_from_db()
        self.assertEqual(product.plu_code, "14267")
        self.assertEqual(item.contagens, [])
        self.assertEqual(item.quantidade, Decimal("123.456"))

        post_data = {
            "action": "save",
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-id": str(item.pk),
            "form-0-count_1": "100.000",
            "form-0-count_2": "20.000",
            "form-0-new_count": "5.500",
        }
        response = self.client.post(reverse("estoque:inventory_collector"), data=post_data)
        self.assertEqual(response.status_code, 302)

        item.refresh_from_db()
        self.assertEqual(item.contagens, [Decimal("100.000"), Decimal("20.000"), Decimal("5.500")])
        self.assertEqual(item.quantidade, Decimal("125.500"))

        # Adiciona nova contagem incremental mantendo as anteriores
        post_data.update({
            "form-0-count_1": "100.000",
            "form-0-count_2": "20.000",
            "form-0-new_count": "2.500",
        })
        response = self.client.post(reverse("estoque:inventory_collector"), data=post_data)
        self.assertEqual(response.status_code, 302)

        item.refresh_from_db()
        self.assertEqual(item.contagens, [Decimal("100.000"), Decimal("20.000"), Decimal("5.500"), Decimal("2.500")])
        self.assertEqual(item.quantidade, Decimal("128.000"))

    def test_export_collector_items_format(self):
        CollectorInventoryItem.objects.all().delete()
        product = Product.objects.create(
            name="Parafuso Teste 5/16",
            code="14267",
            price=Decimal("0"),
        )
        item = CollectorInventoryItem.objects.create(
            codigo_produto="14267",
            descricao=product.name,
            loja="1",
            local="2",
            product=product,
        )
        item.set_counts([Decimal("2.000"), Decimal("3.123")])

        response = self.client.get(reverse("estoque:inventory_collector_export"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertIn("inventario_coletor.txt", response["Content-Disposition"])

        lines = response.content.decode("utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        expected_line = "00000000014267 ;Parafuso Teste ;000001;02;000000000005123"
        self.assertEqual(lines[0], expected_line)

    @patch("estoque.views._load_plu_mapping", return_value={"0000044639": "0142670", "44639": "0142670", "044639": "0142670"})
    def test_import_with_semicolon_reference_matches_product(self, mocked_mapping):
        CollectorInventoryItem.objects.all().delete()
        product = Product.objects.create(
            name="Produto Referência Múltipla",
            code="4461",
            reference="4461;0000044639",
            plu_code="14267",
            price=Decimal("0"),
        )
        content = "0000044639 ;Item referência;000001;01;000000000123000\n"
        upload = SimpleUploadedFile("coletor.txt", content.encode("utf-8"), content_type="text/plain")

        response = self.client.post(
            reverse("estoque:inventory_collector"),
            {"action": "import", "arquivo": upload},
        )
        self.assertEqual(response.status_code, 302)

        item = CollectorInventoryItem.objects.get()
        self.assertEqual(item.product, product)
        self.assertEqual(item.descricao, "Item referência")
        self.assertEqual(item.plu_code, "14267")
        product.refresh_from_db()
        self.assertEqual(product.plu_code, "14267")

    @patch("estoque.views._load_plu_mapping", return_value={})
    def test_import_uses_existing_product_plu_without_lookup(self, mocked_mapping):
        CollectorInventoryItem.objects.all().delete()
        product = Product.objects.create(
            name="Produto PLU local",
            code="9999",
            plu_code="PLU-LOCAL",
        )
        content = "9999 ;Item local;000001;01;000000000001000\n"
        upload = SimpleUploadedFile("coletor.txt", content.encode("utf-8"), content_type="text/plain")

        response = self.client.post(
            reverse("estoque:inventory_collector"),
            {"action": "import", "arquivo": upload},
        )
        self.assertEqual(response.status_code, 302)
        item = CollectorInventoryItem.objects.get()
        self.assertEqual(item.plu_code, "PLU-LOCAL")

    @patch("estoque.views._load_plu_mapping", return_value={})
    def test_import_deduplicates_items_by_plu_code(self, mocked_mapping):
        CollectorInventoryItem.objects.all().delete()
        Product.objects.create(
            name="Produto Duplicado",
            code="14267",
            plu_code="14267",
            price=Decimal("0"),
        )
        content = (
            "0000000014267 ;Primeira desc;000001;01;000000000001000\n"
            "14267 ;Segunda desc;000001;01;000000000002500\n"
        )
        upload = SimpleUploadedFile("coletor.txt", content.encode("utf-8"), content_type="text/plain")

        response = self.client.post(
            reverse("estoque:inventory_collector"),
            {"action": "import", "arquivo": upload},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(CollectorInventoryItem.objects.count(), 1)
        item = CollectorInventoryItem.objects.get()
        self.assertEqual(item.quantidade, Decimal("3.500"))
        self.assertEqual(item.plu_code, "14267")
        self.assertEqual(item.codigo_produto, "0000000014267")
        self.assertEqual(item.descricao, "Primeira desc")

    def test_finalize_inventory_sets_zero_for_missing_counts(self):
        CollectorInventoryItem.objects.all().delete()
        product = Product.objects.create(name="Produto Fechamento", code="900")
        item_with_counts = CollectorInventoryItem.objects.create(
            codigo_produto="900",
            descricao="Antigo",
            loja="1",
            local="A1",
            product=product,
            contagens=[Decimal("1.000"), Decimal("2.000")],
        )
        item_sem_contagem = CollectorInventoryItem.objects.create(
            codigo_produto="901",
            descricao="Outro",
            loja="1",
            local="A2",
        )

        response = self.client.post(
            reverse("estoque:inventory_collector"),
            {"action": "finalize"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        item_with_counts.refresh_from_db()
        item_sem_contagem.refresh_from_db()
        self.assertIsNotNone(item_with_counts.fechado_em)
        self.assertEqual(item_with_counts.quantidade, Decimal("3.000"))
        self.assertIsNotNone(item_sem_contagem.fechado_em)
        self.assertEqual(item_sem_contagem.quantidade, ZERO_DECIMAL)

    def test_clear_inventory_deletes_items(self):
        CollectorInventoryItem.objects.create(
            codigo_produto="123",
            descricao="Item apagar",
            loja="1",
            local="01",
        )
        response = self.client.post(
            reverse("estoque:inventory_collector"),
            {"action": "clear"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CollectorInventoryItem.objects.exists())
