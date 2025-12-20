from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import models
from django.utils import timezone


class CostParameter(models.Model):
	key = models.SlugField('Identificador', max_length=80, unique=True,
		help_text='Usado em integrações e referências internas (somente letras, números e hífen).')
	label = models.CharField('Nome', max_length=160)
	value = models.DecimalField('Valor', max_digits=12, decimal_places=4, default=Decimal('0'))
	unit = models.CharField('Unidade', max_length=32, blank=True,
		help_text='Ex.: %, R$, unidade etc.')
	is_percentage = models.BooleanField('É percentual?', default=False)
	description = models.TextField('Descrição', blank=True)
	is_active = models.BooleanField('Ativo', default=True)
	created_at = models.DateTimeField('Criado em', auto_now_add=True)
	updated_at = models.DateTimeField('Atualizado em', auto_now=True)
	updated_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		blank=True,
		null=True,
		related_name='cost_parameters_updates',
	)

	class Meta:
		verbose_name = 'Parâmetro de custo'
		verbose_name_plural = 'Parâmetros de custo'
		ordering = ('label',)

	def __str__(self):
		return f'{self.label} ({self.key})'

	def formatted_value(self):
		if self.is_percentage:
			return f'{self.value:.2f}%'
		if self.unit:
			return f'{self.unit} {self.value}'
		return str(self.value)

	def save(self, *args, **kwargs):
		if self.key:
			self.key = self.key.strip().lower()
		super().save(*args, **kwargs)


class CostBatch(models.Model):
	name = models.CharField('Nome do lote', max_length=120)
	description = models.TextField('Descrição', blank=True)
	default_ipi_percent = models.DecimalField('IPI padrão (%)', max_digits=6, decimal_places=2, default=Decimal('0'))
	default_freight_percent = models.DecimalField('Frete padrão (%)', max_digits=6, decimal_places=2, default=Decimal('0'))
	mva_percent = models.DecimalField('MVA (%)', max_digits=6, decimal_places=2, default=Decimal('35'))
	st_percent = models.DecimalField('Carga tributária ST (%)', max_digits=6, decimal_places=2, default=Decimal('24'))
	st_multiplier = models.DecimalField('Multiplicador ST', max_digits=8, decimal_places=4, default=Decimal('1.35'))
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)
	created_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name='cost_batches',
	)

	class Meta:
		verbose_name = 'Lote de custos'
		verbose_name_plural = 'Lotes de custos'
		ordering = ('-created_at',)

	def __str__(self):
		return self.name

	def compute_components(self, *, unit_price: Decimal, ipi_percent: Decimal, freight_percent: Decimal):
		price = unit_price or Decimal('0')
		ipi_percent = ipi_percent or Decimal('0')
		freight_percent = freight_percent or Decimal('0')

		def _percent_value(value):
			if value in (None, ''):
				return Decimal('0')
			return (price * value / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

		ipi_value = _percent_value(ipi_percent)
		freight_value = _percent_value(freight_percent)
		base_total = price + ipi_value + freight_value
		st_value = (base_total * self.st_multiplier * (self.st_percent / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
		replacement_cost = (base_total + st_value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
		return {
			'ipi_value': ipi_value,
			'freight_value': freight_value,
			'st_value': st_value,
			'replacement_cost': replacement_cost,
		}


class CostBatchItem(models.Model):
	batch = models.ForeignKey(CostBatch, related_name='items', on_delete=models.CASCADE)
	supplier_item = models.ForeignKey(
		'products.SupplierProductPrice',
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name='cost_batch_items',
	)
	code = models.CharField('Código', max_length=100)
	description = models.CharField('Descrição', max_length=255, blank=True)
	unit = models.CharField('Unidade', max_length=50, blank=True)
	quantity = models.DecimalField('Quantidade', max_digits=10, decimal_places=3, default=Decimal('1'))
	pack_quantity = models.DecimalField('Qtd. por embal.', max_digits=10, decimal_places=3, blank=True, null=True)
	unit_price = models.DecimalField('Preço de compra', max_digits=14, decimal_places=4, default=Decimal('0'))
	ipi_percent = models.DecimalField('IPI (%)', max_digits=6, decimal_places=2, default=Decimal('0'))
	freight_percent = models.DecimalField('Frete (%)', max_digits=6, decimal_places=2, default=Decimal('0'))
	ipi_value = models.DecimalField('IPI (R$)', max_digits=14, decimal_places=4, default=Decimal('0'))
	freight_value = models.DecimalField('Frete (R$)', max_digits=14, decimal_places=4, default=Decimal('0'))
	st_value = models.DecimalField('ST (R$)', max_digits=14, decimal_places=4, default=Decimal('0'))
	replacement_cost = models.DecimalField('Custo reposição', max_digits=14, decimal_places=4, default=Decimal('0'))
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Item do lote'
		verbose_name_plural = 'Itens do lote'
		unique_together = (('batch', 'code'),)
		ordering = ('code',)

	def __str__(self):
		return f'{self.code} ({self.batch})'

	def sync_from_supplier(self):
		if self.supplier_item:
			self.code = self.supplier_item.code
			self.description = self.supplier_item.description or self.description
			self.unit = self.supplier_item.unit or self.unit
			self.quantity = self.supplier_item.quantity or self.quantity
			self.pack_quantity = self.supplier_item.pack_quantity
			if self.supplier_item.unit_price not in (None, ''):
				self.unit_price = self.supplier_item.unit_price

	def recompute_totals(self):
		ipi_percent = self.ipi_percent if self.ipi_percent is not None else self.batch.default_ipi_percent
		freight_percent = self.freight_percent if self.freight_percent is not None else self.batch.default_freight_percent
		components = self.batch.compute_components(
			unit_price=self.unit_price or Decimal('0'),
			ipi_percent=ipi_percent,
			freight_percent=freight_percent,
		)
		self.ipi_value = components['ipi_value']
		self.freight_value = components['freight_value']
		self.st_value = components['st_value']
		self.replacement_cost = components['replacement_cost']

	def save(self, *args, **kwargs):
		self.recompute_totals()
		super().save(*args, **kwargs)

# Create your models here.
