from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

from companies.models import Company
from products.models import Product, ProductGroup, ProductSubGroup


ZERO_DECIMAL = Decimal("0.00")


class Inventory(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        IN_PROGRESS = "in_progress", "Em contagem"
        CLOSED = "closed", "Fechado"

    name = models.CharField("Nome", max_length=150)
    status = models.CharField("Status", max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField("Observações", blank=True)
    company = models.ForeignKey(Company, related_name="inventories", on_delete=models.CASCADE, null=True, blank=True)
    filter_query = models.CharField("Filtro por texto", max_length=255, blank=True)
    filter_in_stock_only = models.BooleanField("Somente produtos com estoque", default=False)
    filter_below_min_stock = models.BooleanField("Somente abaixo do estoque mínimo", default=False)
    filter_group = models.ForeignKey(
        ProductGroup,
        verbose_name="Grupo de produtos",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_filters",
    )
    filter_subgroup = models.ForeignKey(
        ProductSubGroup,
        verbose_name="Subgrupo de produtos",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_filters",
    )
    selected_products = models.ManyToManyField(
        Product,
        through="InventorySelection",
        related_name="selected_inventories",
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Criado por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventories_created",
    )
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Iniciado por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventories_started",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Fechado por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventories_closed",
    )
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    started_at = models.DateTimeField("Iniciado em", null=True, blank=True)
    closed_at = models.DateTimeField("Fechado em", null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Inventário"
        verbose_name_plural = "Inventários"

    def __str__(self) -> str:
        company = self.company.trade_name or self.company.name if self.company else "Sem empresa"
        return f"{self.name} - {company} ({self.get_status_display()})"

    def can_start(self) -> bool:
        return self.status == self.Status.DRAFT

    def can_close(self) -> bool:
        return self.status == self.Status.IN_PROGRESS

    def _apply_filters(self, qs):
        if self.filter_query:
            from products.utils import filter_products_by_search

            qs = filter_products_by_search(qs, self.filter_query)
        if self.filter_in_stock_only:
            if self.company_id:
                qs = qs.filter(stock_entries__company=self.company, stock_entries__quantity__gt=0)
            else:
                qs = qs.filter(stock__gt=0)
        if self.filter_below_min_stock:
            if self.company_id:
                qs = qs.filter(
                    stock_entries__company=self.company,
                    stock_entries__min_quantity__gt=0,
                    stock_entries__quantity__lt=F('stock_entries__min_quantity'),
                )
            else:
                qs = qs.filter(min_stock__isnull=False, stock__lt=F("min_stock"))
        if self.filter_group_id:
            qs = qs.filter(product_group_id=self.filter_group_id)
        if self.filter_subgroup_id:
            qs = qs.filter(product_subgroup_id=self.filter_subgroup_id)
        return qs.distinct()

    def get_filtered_products(self):
        qs = Product.objects.all().order_by("name")
        return self._apply_filters(qs)

    def get_source_products(self):
        selected_qs = self.selected_products.all().order_by("name")
        if selected_qs.exists():
            return selected_qs
        return self.get_filtered_products()

    def _build_snapshot(self, timestamp) -> Iterable["InventoryItem"]:
        if not self.company:
            raise ValueError("Inventário precisa estar associado a uma empresa.")
        qs = self.get_source_products()
        for product in qs:
            frozen = product.stock_for_company(self.company)
            yield InventoryItem(
                inventory=self,
                product=product,
                frozen_quantity=frozen,
                recorded_at=timestamp,
            )

    def start_inventory(self, user=None) -> None:
        if not self.can_start():
            raise ValueError("Inventário já foi iniciado ou encerrado.")
        if not self.company:
            raise ValueError("Defina a empresa do inventário antes de iniciar a contagem.")

        with transaction.atomic():
            start_ts = timezone.now()
            items = list(self._build_snapshot(start_ts))
            InventoryItem.objects.bulk_create(items, batch_size=500)

            self.status = self.Status.IN_PROGRESS
            self.started_at = start_ts
            if user and not self.started_by:
                self.started_by = user
            self.save(update_fields=["status", "started_at", "started_by"])

    def close_inventory(self, user=None) -> None:
        if not self.can_close():
            raise ValueError("Inventário precisa estar em contagem para ser fechado.")

        with transaction.atomic():
            closed_ts = timezone.now()
            for item in self.items.select_related("product"):
                final_quantity = item.final_quantity
                update_fields = ["closed_at"]
                if final_quantity is None:
                    if item.recount_quantity is not None:
                        final_quantity = item.recount_quantity
                    elif item.counted_quantity is not None:
                        final_quantity = item.counted_quantity
                    else:
                        final_quantity = item.frozen_quantity
                    item.final_quantity = final_quantity
                    update_fields.append("final_quantity")
                item.closed_at = closed_ts
                item.save(update_fields=update_fields)

                product = item.product
                product.update_stock_for_company(self.company, quantity=final_quantity)

            self.status = self.Status.CLOSED
            self.closed_at = closed_ts
            if user and not self.closed_by:
                self.closed_by = user
            self.save(update_fields=["status", "closed_at", "closed_by"])


class InventoryItem(models.Model):
    inventory = models.ForeignKey(Inventory, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, related_name="inventory_items", on_delete=models.PROTECT)
    frozen_quantity = models.DecimalField("Quantidade congelada", max_digits=12, decimal_places=2, default=ZERO_DECIMAL)
    counted_quantity = models.DecimalField("Quantidade contada", max_digits=12, decimal_places=2, null=True, blank=True)
    recount_quantity = models.DecimalField("Quantidade recontada", max_digits=12, decimal_places=2, null=True, blank=True)
    final_quantity = models.DecimalField("Quantidade final", max_digits=12, decimal_places=2, null=True, blank=True)
    recorded_at = models.DateTimeField("Registrado em", default=timezone.now, editable=False)
    closed_at = models.DateTimeField("Encerrado em", null=True, blank=True)

    class Meta:
        unique_together = ("inventory", "product")
        ordering = ("product__name",)
        verbose_name = "Item de inventário"
        verbose_name_plural = "Itens de inventário"

    def __str__(self) -> str:
        return f"{self.product} - {self.inventory.name}"

    @property
    def effective_quantity(self) -> Decimal:
        if self.final_quantity is not None:
            return self.final_quantity
        if self.recount_quantity is not None:
            return self.recount_quantity
        if self.counted_quantity is not None:
            return self.counted_quantity
        return self.frozen_quantity

    @property
    def difference(self) -> Decimal:
        return self.effective_quantity - self.frozen_quantity


class InventorySelection(models.Model):
    inventory = models.ForeignKey(Inventory, related_name="selection_entries", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, related_name="inventory_selections", on_delete=models.CASCADE)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("inventory", "product")
        verbose_name = "Produto selecionado"
        verbose_name_plural = "Produtos selecionados"

    def __str__(self) -> str:
        return f"{self.inventory.name} -> {self.product}"


class CollectorInventoryItem(models.Model):
    codigo_produto = models.CharField("Código do produto", max_length=20)
    descricao = models.CharField("Descrição", max_length=255, blank=True)
    product = models.ForeignKey(
        Product,
        verbose_name="Produto associado",
        related_name="collector_inventory_items",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    loja = models.CharField("Loja", max_length=10)
    local = models.CharField("Local", max_length=10)
    quantidade = models.DecimalField(
        "Quantidade", max_digits=15, decimal_places=3, default=ZERO_DECIMAL
    )
    plu_code = models.CharField("Código PLU", max_length=50, blank=True)
    contagens = ArrayField(
        base_field=models.DecimalField(max_digits=15, decimal_places=3),
        verbose_name="Contagens registradas",
        default=list,
        blank=True,
    )
    importado_em = models.DateTimeField("Importado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("Atualizado em", auto_now=True)
    fechado_em = models.DateTimeField("Encerrado em", null=True, blank=True)

    class Meta:
        unique_together = ("plu_code", "loja", "local")
        ordering = ("loja", "local", "codigo_produto")
        verbose_name = "Item do coletor de inventário"
        verbose_name_plural = "Itens do coletor de inventário"

    def __str__(self) -> str:
        label = self.product.name if self.product else (self.descricao or self.codigo_produto)
        return f"{label} ({self.loja}/{self.local})"

    @staticmethod
    def _normalize(value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(value)
        return value.quantize(Decimal("0.001"))

    def set_counts(self, counts: list[Decimal]) -> None:
        normalized = [self._normalize(value) for value in counts if value is not None]
        self.contagens = normalized
        total = sum(normalized, ZERO_DECIMAL) if normalized else ZERO_DECIMAL
        self.quantidade = total.quantize(Decimal("0.001"))
        self.save(update_fields=["contagens", "quantidade", "atualizado_em"])

    def finalize(self) -> None:
        """
        Garante que a quantidade reflita a soma das contagens e marca o item como encerrado.
        Itens sem contagem passam a valer zero.
        """
        counts = [value for value in self.contagens if value is not None]
        if counts:
            total = sum(counts, ZERO_DECIMAL).quantize(Decimal("0.001"))
        else:
            total = ZERO_DECIMAL
        fields = []
        if self.quantidade != total:
            self.quantidade = total
            fields.append("quantidade")
        self.fechado_em = timezone.now()
        fields.append("fechado_em")
        fields.append("atualizado_em")
        self.save(update_fields=fields)

    @property
    def primeira_contagem(self) -> Decimal | None:
        return self.contagens[0] if self.contagens else None

    @property
    def segunda_contagem(self) -> Decimal | None:
        return self.contagens[1] if len(self.contagens) > 1 else None

    @property
    def outras_contagens(self) -> list[Decimal]:
        return self.contagens[2:] if len(self.contagens) > 2 else []
