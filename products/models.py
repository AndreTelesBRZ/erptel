from decimal import Decimal, ROUND_HALF_UP
from django.db import models
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from companies.models import Company

from core.utils.documents import (
	format_cnpj,
	format_cpf,
	normalize_cnpj,
	normalize_cpf,
)

ZERO_DECIMAL = Decimal('0.00')


class ProductGroup(models.Model):
	name = models.CharField(max_length=200)
	parent_group = models.ForeignKey('self', related_name='children', on_delete=models.CASCADE, null=True, blank=True)

	class Meta:
		verbose_name = 'Grupo de Produtos'
		verbose_name_plural = 'Grupos de Produtos'
		unique_together = ('parent_group', 'name')

	def __str__(self):
		if self.parent_group:
			return f"{self.parent_group} > {self.name}"
		return self.name


class ProductSubGroup(models.Model):
	group = models.ForeignKey(ProductGroup, related_name='subgroups', on_delete=models.CASCADE)
	parent_subgroup = models.ForeignKey('self', related_name='children', on_delete=models.CASCADE, null=True, blank=True)
	name = models.CharField(max_length=200)

	class Meta:
		verbose_name = 'Subgrupo de Produtos'
		verbose_name_plural = 'Subgrupos de Produtos'
		unique_together = (
			('group', 'parent_subgroup', 'name'),
		)

	def __str__(self):
		return self.full_name

	def clean(self):
		super().clean()
		if self.parent_subgroup:
			if self.parent_subgroup_id == self.pk:
				raise ValidationError({'parent_subgroup': 'O subgrupo não pode ser pai de si mesmo.'})
			if self.parent_subgroup.group_id != self.group_id:
				raise ValidationError({'parent_subgroup': 'O subgrupo pai deve pertencer ao mesmo grupo.'})
			# prevent cyclic assignments
			ancestor = self.parent_subgroup
			while ancestor:
				if ancestor.pk == self.pk:
					raise ValidationError({'parent_subgroup': 'Não é possível criar um ciclo de subgrupos.'})
				ancestor = ancestor.parent_subgroup

	@property
	def full_name(self):
		parts = [self.name]
		parent = self.parent_subgroup
		while parent:
			parts.append(parent.name)
			parent = parent.parent_subgroup
		return f"{self.group} / {' / '.join(reversed(parts))}"

	def get_ancestors(self):
		ancestors = []
		parent = self.parent_subgroup
		while parent:
			ancestors.append(parent)
			parent = parent.parent_subgroup
		return ancestors


# New related models inferred from spreadsheet
class Supplier(models.Model):
	class PersonType(models.TextChoices):
		INDIVIDUAL = 'F', 'Pessoa Física'
		LEGAL = 'J', 'Pessoa Jurídica'

	name = models.CharField(max_length=200)
	person_type = models.CharField('Tipo de pessoa', max_length=1, choices=PersonType.choices, default=PersonType.LEGAL)
	document = models.CharField('CPF/CNPJ', max_length=14, unique=True)
	code = models.CharField('Código', max_length=14, unique=True)
	state_registration = models.CharField('Inscrição estadual', max_length=30, blank=True)
	email = models.EmailField('E-mail', blank=True)
	phone = models.CharField('Telefone', max_length=30, blank=True)
	address = models.CharField('Endereço', max_length=255, blank=True)
	number = models.CharField('Número', max_length=20, blank=True)
	complement = models.CharField('Complemento', max_length=100, blank=True)
	district = models.CharField('Bairro', max_length=100, blank=True)
	city = models.CharField('Cidade', max_length=100, blank=True)
	state = models.CharField('UF', max_length=2, blank=True)
	zip_code = models.CharField('CEP', max_length=12, blank=True)
	notes = models.TextField('Observações', blank=True)
	created_at = models.DateTimeField('Criado em', auto_now_add=True)
	updated_at = models.DateTimeField('Atualizado em', auto_now=True)

	class Meta:
		verbose_name = 'Fornecedor'
		verbose_name_plural = 'Fornecedores'
		ordering = ('name',)

	def __str__(self):
		return self.name

	@property
	def formatted_document(self):
		if self.person_type == self.PersonType.LEGAL:
			return format_cnpj(self.document)
		return format_cpf(self.document)

	def _sync_document_fields(self):
		if not self.document:
			raise ValidationError({'document': 'Informe o CPF ou CNPJ.'})
		try:
			if self.person_type == self.PersonType.LEGAL:
				digits = normalize_cnpj(self.document)
			else:
				digits = normalize_cpf(self.document)
		except ValueError as exc:
			raise ValidationError({'document': str(exc)})
		self.document = digits
		self.code = digits

	def clean(self):
		super().clean()
		if self.document:
			self._sync_document_fields()

	def save(self, *args, **kwargs):
		self._sync_document_fields()
		super().save(*args, **kwargs)


class Brand(models.Model):
	name = models.CharField(max_length=200)

	class Meta:
		verbose_name = 'Marca'
		verbose_name_plural = 'Marcas'

	def __str__(self):
		return self.name


class Category(models.Model):
	name = models.CharField(max_length=200)

	class Meta:
		verbose_name = 'Categoria'
		verbose_name_plural = 'Categorias'

	def __str__(self):
		return self.name


class Department(models.Model):
	name = models.CharField(max_length=200)

	class Meta:
		verbose_name = 'Departamento'
		verbose_name_plural = 'Departamentos'

	def __str__(self):
		return self.name


class Tag(models.Model):
	name = models.CharField(max_length=200)

	class Meta:
		verbose_name = 'Tag'
		verbose_name_plural = 'Tags'

	def __str__(self):
		return self.name


class Tax(models.Model):
	name = models.CharField(max_length=200)
	code = models.CharField(max_length=200, blank=True, null=True)

	class Meta:
		verbose_name = 'Tributo'
		verbose_name_plural = 'Tributos'

	def __str__(self):
		return self.name


class Volume(models.Model):
	description = models.CharField(max_length=200)

	class Meta:
		verbose_name = 'Volume'
		verbose_name_plural = 'Volumes'

	def __str__(self):
		return self.description


class UnitOfMeasure(models.Model):
	code = models.CharField(max_length=50)
	name = models.CharField(max_length=100, blank=True, null=True)

	class Meta:
		verbose_name = 'Unidade de Medida'
		verbose_name_plural = 'Unidades de Medida'

	def __str__(self):
		return self.code


class ProductImage(models.Model):
	product = models.ForeignKey('Product', related_name='images', on_delete=models.CASCADE)
	# store uploaded images in MEDIA (image) and keep `url` for external image references
	image = models.ImageField(upload_to='product_images/', blank=True, null=True)
	url = models.TextField(blank=True, null=True)

	class Meta:
		verbose_name = 'Imagem do Produto'
		verbose_name_plural = 'Imagens dos Produtos'

	def __str__(self):
		return f"Imagem de {self.product}"


class PriceAdjustmentBatch(models.Model):
	class Status(models.TextChoices):
		PENDING = 'pending', 'Pendente'
		APPROVED = 'approved', 'Aprovado'
		REJECTED = 'rejected', 'Rejeitado'

	class Rule(models.TextChoices):
		INCREASE_PERCENT = 'increase_percent', 'Aumentar % sobre o preço atual'
		SET_MARGIN = 'set_margin', 'Aplicar margem (%) sobre o custo'

	created_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name='price_adjustment_batches',
	)
	status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
	rule_type = models.CharField(max_length=30, choices=Rule.choices)
	parameters = models.JSONField(blank=True, default=dict)
	notes = models.TextField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Lote de reajuste de preço'
		verbose_name_plural = 'Lotes de reajuste de preço'
		ordering = ('-created_at',)

	def __str__(self):
		return f"Lote #{self.pk} - {self.get_rule_type_display()} ({self.get_status_display()})"

	@property
	def item_count(self):
		return self.items.count()

	def refresh_status(self):
		statuses = set(self.items.values_list('status', flat=True))
		if PriceAdjustmentItem.Status.PENDING in statuses:
			new_status = self.Status.PENDING
		elif PriceAdjustmentItem.Status.APPROVED in statuses:
			new_status = self.Status.APPROVED
		elif PriceAdjustmentItem.Status.REJECTED in statuses:
			new_status = self.Status.REJECTED
		elif statuses:
			new_status = self.Status.REJECTED
		else:
			new_status = self.Status.PENDING
		if self.status != new_status:
			self.status = new_status
			self.save(update_fields=['status', 'updated_at'])



class PriceAdjustmentItem(models.Model):
	class Status(models.TextChoices):
		PENDING = 'pending', 'Pendente'
		APPROVED = 'approved', 'Aprovado'
		REJECTED = 'rejected', 'Rejeitado'
		SKIPPED = 'skipped', 'Ignorado'

	batch = models.ForeignKey(PriceAdjustmentBatch, related_name='items', on_delete=models.CASCADE)
	product = models.ForeignKey('Product', related_name='price_adjustments', on_delete=models.CASCADE)
	status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
	message = models.CharField(max_length=255, blank=True)
	old_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
	new_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
	cost_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
	old_margin_percent = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
	new_margin_percent = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
	rule_snapshot = models.JSONField(blank=True, default=dict)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		verbose_name = 'Item do reajuste de preço'
		verbose_name_plural = 'Itens do reajuste de preço'
		ordering = ('product__name',)

	def __str__(self):
		return f"{self.product} ({self.batch})"

	def apply_new_price(self):
		"""Persist the suggested price on the associated product."""
		if self.new_price is None:
			raise ValueError('Não há novo preço calculado para aplicar.')
		product = self.product
		product.price = self.new_price
		product.save(update_fields=['price'])

	def revert_price(self):
		"""Restore the original price only when the product still has the suggested value."""
		if self.old_price is None or self.new_price is None:
			return
		product = self.product
		if product.price == self.new_price:
			product.price = self.old_price
			product.save(update_fields=['price'])


class SupplierProductPrice(models.Model):
	supplier = models.ForeignKey(Supplier, related_name='catalog_items', on_delete=models.CASCADE)
	product = models.ForeignKey('Product', related_name='supplier_catalogs', on_delete=models.SET_NULL, blank=True, null=True)
	code = models.CharField('Código', max_length=100)
	description = models.CharField('Descrição', max_length=255)
	unit = models.CharField('Unidade', max_length=50, blank=True)
	quantity = models.DecimalField('Qtd. etiq.', max_digits=10, decimal_places=3, blank=True, null=True)
	pack_quantity = models.DecimalField('Qtd. por embalagem', max_digits=10, decimal_places=3, blank=True, null=True)
	unit_price = models.DecimalField('Valor unitário', max_digits=14, decimal_places=4)
	ipi_percent = models.DecimalField('IPI (%)', max_digits=6, decimal_places=3, blank=True, null=True)
	freight_percent = models.DecimalField('Frete (%)', max_digits=6, decimal_places=3, blank=True, null=True)
	st_percent = models.DecimalField('ST (%)', max_digits=6, decimal_places=3, blank=True, null=True)
	replacement_cost = models.DecimalField('Custo reposição', max_digits=14, decimal_places=4, blank=True, null=True)
	valid_from = models.DateField('Início vigência')
	valid_until = models.DateField('Fim vigência', blank=True, null=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Preço de fornecedor'
		verbose_name_plural = 'Preços de fornecedores'
		ordering = ('supplier', 'code', '-valid_from')
		unique_together = (
			('supplier', 'code', 'valid_from'),
		)

	def __str__(self):
		return f"{self.supplier} - {self.code} ({self.valid_from:%d/%m/%Y})"


class PriceAdjustmentLog(models.Model):
	class Action(models.TextChoices):
		APPROVED = PriceAdjustmentItem.Status.APPROVED, 'Aprovado'
		REJECTED = PriceAdjustmentItem.Status.REJECTED, 'Rejeitado'
		PENDING = PriceAdjustmentItem.Status.PENDING, 'Pendente'

	item = models.ForeignKey(PriceAdjustmentItem, related_name='logs', on_delete=models.CASCADE)
	batch = models.ForeignKey(PriceAdjustmentBatch, related_name='logs', on_delete=models.CASCADE)
	product = models.ForeignKey('Product', related_name='price_adjustment_logs', on_delete=models.CASCADE)
	action = models.CharField(max_length=20, choices=Action.choices)
	decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
	old_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
	new_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
	notes = models.CharField(max_length=255, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		verbose_name = 'Histórico de reajuste'
		verbose_name_plural = 'Históricos de reajuste'
		ordering = ('-created_at',)

	def __str__(self):
		return f"{self.product} - {self.get_action_display()} em {self.created_at:%d/%m/%Y %H:%M}"


class Product(models.Model):
	name = models.CharField(max_length=200)
	code = models.CharField(max_length=100, blank=True, null=True)  # Código
	description = models.TextField(blank=True)
	short_description = models.CharField(max_length=255, blank=True, null=True)
	unit = models.CharField(max_length=50, blank=True, null=True)  # Unidade
	ncm = models.CharField(max_length=50, blank=True, null=True)
	origin = models.CharField(max_length=10, blank=True, null=True)  # Origem
	price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
	fixed_ipi = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
	status = models.CharField(max_length=50, blank=True, null=True)
	stock = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
	allow_fractional_sale = models.BooleanField('Permite venda fracionada', default=False)
	cost_price = models.DecimalField(max_digits=14, decimal_places=4, blank=True, null=True)
	cost_price_updated_at = models.DateTimeField('Atualizado custo em', blank=True, null=True, editable=False)
	cost_price_company = models.ForeignKey(
		'companies.Company',
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		editable=False,
		related_name='cost_price_products',
		verbose_name='Empresa do último custo',
	)
	reference = models.CharField(max_length=200, blank=True, null=True)
	supplier_code = models.CharField(max_length=200, blank=True, null=True)
	plu_code = models.CharField('Código PLU', max_length=50, blank=True, null=True)
	supplier = models.CharField(max_length=200, blank=True, null=True)
	location = models.CharField(max_length=200, blank=True, null=True)
	max_stock = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
	min_stock = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
	weight_net = models.DecimalField(max_digits=10, decimal_places=3, blank=True, null=True)
	weight_gross = models.DecimalField(max_digits=10, decimal_places=3, blank=True, null=True)
	lifecycle_start_date = models.DateField('Início de linha', blank=True, null=True)
	lifecycle_end_date = models.DateField('Fim de linha', blank=True, null=True)
	gtin = models.CharField(max_length=100, blank=True, null=True)
	gtin_package = models.CharField(max_length=100, blank=True, null=True)
	width = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
	height = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
	depth = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
	expiration_date = models.DateField(blank=True, null=True)
	supplier_description = models.TextField(blank=True, null=True)
	complement_description = models.TextField(blank=True, null=True)
	items_per_box = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
	variation = models.CharField(max_length=200, blank=True, null=True)
	production_type = models.CharField(max_length=200, blank=True, null=True)
	ipi_class = models.CharField(max_length=200, blank=True, null=True)
	service_list_code = models.CharField(max_length=200, blank=True, null=True)
	item_type = models.CharField(max_length=200, blank=True, null=True)
	tags = models.CharField(max_length=500, blank=True, null=True)
	taxes = models.CharField(max_length=500, blank=True, null=True)
	parent_code = models.CharField(max_length=200, blank=True, null=True)
	integration_code = models.CharField(max_length=200, blank=True, null=True)
	product_group = models.ForeignKey(ProductGroup, related_name='products', on_delete=models.SET_NULL, blank=True, null=True)
	product_subgroup = models.ForeignKey(ProductSubGroup, related_name='products', on_delete=models.SET_NULL, blank=True, null=True)
	brand = models.CharField(max_length=200, blank=True, null=True)
	brand_obj = models.ForeignKey('Brand', related_name='products', on_delete=models.SET_NULL, blank=True, null=True)
	cest = models.CharField(max_length=200, blank=True, null=True)
	volumes = models.CharField(max_length=200, blank=True, null=True)
	volumes_obj = models.ForeignKey('Volume', related_name='products', on_delete=models.SET_NULL, blank=True, null=True)
	external_images = models.TextField(blank=True, null=True)
	external_link = models.URLField(blank=True, null=True)
	warranty_months = models.IntegerField(blank=True, null=True)
	clone_parent = models.BooleanField(default=False)
	condition = models.CharField(max_length=100, blank=True, null=True)
	free_shipping = models.BooleanField(default=False)
	fci_number = models.CharField(max_length=200, blank=True, null=True)
	video = models.CharField(max_length=500, blank=True, null=True)
	department = models.CharField(max_length=200, blank=True, null=True)
	department_obj = models.ForeignKey('Department', related_name='products', on_delete=models.SET_NULL, blank=True, null=True)
	unit_of_measure = models.CharField(max_length=50, blank=True, null=True)
	unit_of_measure_obj = models.ForeignKey('UnitOfMeasure', related_name='products', on_delete=models.SET_NULL, blank=True, null=True)
	icms_base_st = models.DecimalField(max_digits=14, decimal_places=4, blank=True, null=True)
	icms_st_value = models.DecimalField(max_digits=14, decimal_places=4, blank=True, null=True)
	icms_substitute_value = models.DecimalField(max_digits=14, decimal_places=4, blank=True, null=True)
	category = models.CharField(max_length=200, blank=True, null=True)
	category_obj = models.ForeignKey('Category', related_name='products', on_delete=models.SET_NULL, blank=True, null=True)
	additional_info = models.TextField(blank=True, null=True)
	supplier_obj = models.ForeignKey('Supplier', related_name='products', on_delete=models.SET_NULL, blank=True, null=True)
	companies = models.ManyToManyField('companies.Company', related_name='products', blank=True)
	pricing_base_cost = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)
	pricing_variable_expense_percent = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
	pricing_fixed_expense_percent = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
	pricing_tax_percent = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
	pricing_desired_margin_percent = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
	pricing_markup_factor = models.DecimalField(max_digits=9, decimal_places=4, blank=True, null=True)
	pricing_suggested_price = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)

	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		verbose_name = 'Produto'
		verbose_name_plural = 'Produtos'
		ordering = ('reference', 'supplier_code', '-created_at')
		constraints = [
			models.UniqueConstraint(fields=['code'], name='uniq_product_code')
		]

	def __str__(self):
		return f"{self.name} ({self.code or '—'})"

	@staticmethod
	def normalize_code(code):
			"""Return a canonical representation for product codes.
			- If the code is purely numeric (possibly with leading zeros), drop leading zeros
			  by casting to int ("0002820" -> "2820").
			- Otherwise, trim whitespace and uppercase for consistency.
			"""
			if code is None:
				return None
			s = str(code).strip()
			if s == '':
				return None
			# numeric-only (allow leading zeros)
			if re.fullmatch(r"0*[0-9]+", s):
				# preserve 0 if the value is actually zero
				try:
					return str(int(s))
				except Exception:
					pass
			# fallback: normalize casing/spaces for mixed codes
			return s.upper()

	def calculate_pricing(self, force=False):
		base_cost = self.pricing_base_cost
		if base_cost in (None, ''):
			base_cost = self.cost_price
		if base_cost in (None, ''):
			return
		try:
			base_cost = Decimal(base_cost)
		except Exception:
			return

		percent_fields = [
			self.pricing_variable_expense_percent,
			self.pricing_fixed_expense_percent,
			self.pricing_tax_percent,
			self.pricing_desired_margin_percent,
		]
		total_percent = Decimal('0')
		for value in percent_fields:
			if value not in (None, ''):
				try:
					 total_percent += Decimal(value)
				except Exception:
					pass

		if total_percent >= Decimal('99.9999'):
			return
		divisor = Decimal('1') - (total_percent / Decimal('100'))
		if divisor <= Decimal('0'):
			return
		markup = (Decimal('1') / divisor).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
		price = (base_cost * markup).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
		if force or not self.pricing_markup_factor:
			self.pricing_markup_factor = markup
		if force or not self.pricing_suggested_price:
			self.pricing_suggested_price = price

	@property
	def is_lifecycle_active(self):
		if self.lifecycle_end_date:
			today = timezone.localdate()
			if self.lifecycle_end_date <= today:
				return False
		return True

	@property
	def lifecycle_status_display(self):
		return 'Ativo' if self.is_lifecycle_active else 'Fora de linha'

	def save(self, *args, **kwargs):
		# Normalize code on every save to keep consistency
		if self.code is not None:
			self.code = Product.normalize_code(self.code)
		if self.reference is not None:
			self.reference = Product.normalize_code(self.reference)
		if self.supplier_code is not None:
			self.supplier_code = Product.normalize_code(self.supplier_code)
		self.calculate_pricing(force=not (self.pricing_markup_factor and self.pricing_suggested_price))
		super().save(*args, **kwargs)

	def refresh_total_stock(self):
		total = self.stock_entries.aggregate(
			total=Coalesce(Sum('quantity'), Value(ZERO_DECIMAL))
		)['total'] or ZERO_DECIMAL
		Product.objects.filter(pk=self.pk).update(stock=total)
		self.stock = total
		return total

	def stock_for_company(self, company: Company | int | None) -> Decimal:
		if not company:
			return self.stock if self.stock is not None else ZERO_DECIMAL
		company_id = company if isinstance(company, int) else getattr(company, 'pk', None)
		if not company_id:
			return ZERO_DECIMAL
		entry = self.stock_entries.filter(company_id=company_id).first()
		return entry.quantity if entry else ZERO_DECIMAL

	def update_stock_for_company(self, company: Company, *, quantity: Decimal | None = None, delta: Decimal | None = None):
		if not company:
			return
		entry, _ = ProductStock.objects.get_or_create(
			product=self,
			company=company,
			defaults={'quantity': ZERO_DECIMAL},
		)
		current = entry.quantity or ZERO_DECIMAL
		if quantity is not None:
			entry.quantity = quantity
		elif delta is not None:
			entry.quantity = current + delta
		entry.save()
		if company not in self.companies.all():
			self.companies.add(company)
		self.refresh_total_stock()


class ProductStock(models.Model):
	product = models.ForeignKey(Product, related_name='stock_entries', on_delete=models.CASCADE)
	company = models.ForeignKey(Company, related_name='product_stocks', on_delete=models.CASCADE)
	quantity = models.DecimalField('Quantidade', max_digits=14, decimal_places=2, default=ZERO_DECIMAL)
	min_quantity = models.DecimalField('Estoque mínimo', max_digits=14, decimal_places=2, default=ZERO_DECIMAL)
	max_quantity = models.DecimalField('Estoque máximo', max_digits=14, decimal_places=2, default=ZERO_DECIMAL)
	created_at = models.DateTimeField('Criado em', auto_now_add=True)
	updated_at = models.DateTimeField('Atualizado em', auto_now=True)

	class Meta:
		verbose_name = 'Estoque por empresa'
		verbose_name_plural = 'Estoques por empresa'
		unique_together = (('product', 'company'),)
		ordering = ('product__name', 'company__name')

	def __str__(self):
		return f'{self.product} @ {self.company} = {self.quantity}'

	def save(self, *args, **kwargs):
		if self.quantity is None:
			self.quantity = ZERO_DECIMAL
		super().save(*args, **kwargs)
		self.product.refresh_total_stock()

	def delete(self, *args, **kwargs):
		product = self.product
		super().delete(*args, **kwargs)
		product.refresh_total_stock()




class ProdutoSync(models.Model):
    codigo = models.CharField(primary_key=True, max_length=50, db_column='codigo')
    descricao = models.TextField(null=True, blank=True, db_column='descricao_completa')
    referencia = models.CharField(max_length=100, null=True, blank=True, db_column='referencia')
    secao = models.CharField(max_length=20, null=True, blank=True, db_column='secao')
    grupo = models.CharField(max_length=20, null=True, blank=True, db_column='grupo')
    subgrupo = models.CharField(max_length=20, null=True, blank=True, db_column='subgrupo')
    unidade = models.CharField(max_length=20, null=True, blank=True, db_column='unidade')
    ean = models.CharField(max_length=50, null=True, blank=True, db_column='ean')
    plu = models.CharField(max_length=50, null=True, blank=True, db_column='plu')
    preco_normal = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True, db_column='preco_normal')
    preco_promocional_1 = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True, db_column='preco_promocao1')
    preco_promocional_2 = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True, db_column='preco_promocao2')
    custo = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True, db_column='custo')
    estoque_disponivel = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True, db_column='estoque_disponivel')
    loja = models.CharField(max_length=20, null=True, blank=True, db_column='loja')
    row_hash = models.TextField(null=True, blank=True, db_column='row_hash')

    class Meta:
        managed = False
        db_table = "erp_produtos_sync"
        unique_together = (('codigo', 'loja'),)
