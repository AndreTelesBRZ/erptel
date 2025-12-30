from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from companies.models import Company
from core.utils.documents import format_cpf, normalize_cpf


class Quote(models.Model):
	class Status(models.TextChoices):
		DRAFT = 'draft', _('Rascunho')
		SENT = 'sent', _('Enviado')
		APPROVED = 'approved', _('Aprovado')
		DECLINED = 'declined', _('Recusado')
		CONVERTED = 'converted', _('Convertido')

	number = models.CharField(_('Número'), max_length=20, blank=True)
	client = models.ForeignKey('clients.Client', verbose_name=_('Cliente'), on_delete=models.PROTECT, related_name='quotes')
	company = models.ForeignKey(Company, verbose_name=_('Empresa'), related_name='quotes', on_delete=models.CASCADE, null=True, blank=True)
	salesperson = models.ForeignKey(
		'sales.Salesperson',
		verbose_name=_('Vendedor'),
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name='quotes',
	)
	valid_until = models.DateField(_('Válido até'), blank=True, null=True)
	status = models.CharField(_('Status'), max_length=20, choices=Status.choices, default=Status.DRAFT)
	notes = models.TextField(_('Observações'), blank=True)
	created_at = models.DateTimeField(_('Criado em'), auto_now_add=True)
	updated_at = models.DateTimeField(_('Atualizado em'), auto_now=True)
	loja_codigo = models.CharField(_('Loja'), max_length=10, default='00001')

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['number', 'loja_codigo'], name='uniq_sales_quote_number_loja'),
		]
		ordering = ['-created_at']
		verbose_name = _('Orçamento')
		verbose_name_plural = _('Orçamentos')

	def __str__(self):
		return f'Orçamento {self.number}'

	def save(self, *args, **kwargs):
		if not self.number:
			self.number = self._generate_number()
		super().save(*args, **kwargs)

	def _generate_number(self):
		return self.get_next_number(company=self.company_id or self.company, loja_codigo=self.loja_codigo)

	@classmethod
	def get_next_number(cls, company=None, loja_codigo=None):
		prefix = timezone.now().strftime('OR%y')
		qs = cls.objects.filter(number__startswith=prefix)
		company_id = None
		if company is not None:
			company_id = getattr(company, 'pk', None) if not isinstance(company, int) else company
		if company_id:
			qs = qs.filter(company_id=company_id)
		if loja_codigo:
			qs = qs.filter(loja_codigo=loja_codigo)
		last = qs.order_by('-number').first()
		sequence = 1
		if last:
			try:
				sequence = int(last.number[-4:]) + 1
			except ValueError:
				sequence = 1
		return f'{prefix}{sequence:04d}'

	@property
	def total_amount(self) -> Decimal:
		return sum((item.total_amount for item in self.items.all() if item.product), Decimal('0.00'))


class QuoteItem(models.Model):
	quote = models.ForeignKey(Quote, related_name='items', on_delete=models.CASCADE)
	product = models.ForeignKey('products.Product', verbose_name=_('Produto'), on_delete=models.PROTECT, blank=True, null=True)
	description = models.CharField(_('Descrição'), max_length=255, blank=True)
	quantity = models.DecimalField(_('Quantidade'), max_digits=10, decimal_places=2, default=Decimal('1.00'))
	delivery_days = models.PositiveIntegerField(_('Prazo de entrega (dias)'), blank=True, null=True)
	unit_price = models.DecimalField(_('Preço unitário'), max_digits=12, decimal_places=2, default=Decimal('0.00'))
	discount = models.DecimalField(_('Desconto'), max_digits=12, decimal_places=2, default=Decimal('0.00'))
	sort_order = models.PositiveIntegerField(_('Ordem'), default=0)
	loja_codigo = models.CharField(_('Loja'), max_length=10, default='00001')

	class Meta:
		ordering = ['sort_order', 'pk']
		verbose_name = _('Item de orçamento')
		verbose_name_plural = _('Itens de orçamento')

	def __str__(self):
		return self.description or (self.product.name if self.product else 'Item')

	@property
	def effective_description(self):
		if self.description:
			return self.description
		if self.product:
			return self.product.name
		return ''

	@property
	def total_amount(self) -> Decimal:
		total = (self.quantity or Decimal('0')) * (self.unit_price or Decimal('0'))
		return max(total - (self.discount or Decimal('0')), Decimal('0'))


class Order(models.Model):
	class Status(models.TextChoices):
		DRAFT = 'draft', _('Aberto')
		CONFIRMED = 'confirmed', _('Confirmado')
		INVOICED = 'invoiced', _('Faturado')
		SHIPPED = 'shipped', _('Enviado')
		CANCELLED = 'cancelled', _('Cancelado')

	number = models.CharField(_('Número'), max_length=20, blank=True)
	client = models.ForeignKey('clients.Client', verbose_name=_('Cliente'), on_delete=models.PROTECT, related_name='orders')
	company = models.ForeignKey(Company, verbose_name=_('Empresa'), related_name='orders', on_delete=models.CASCADE, null=True, blank=True)
	quote = models.ForeignKey(Quote, verbose_name=_('Orçamento de origem'), related_name='orders', on_delete=models.SET_NULL, blank=True, null=True)
	issue_date = models.DateField(_('Data de emissão'), default=timezone.localdate)
	status = models.CharField(_('Status'), max_length=20, choices=Status.choices, default=Status.DRAFT)
	payment_terms = models.CharField(_('Condições de pagamento'), max_length=200, blank=True)
	notes = models.TextField(_('Observações'), blank=True)
	created_at = models.DateTimeField(_('Criado em'), auto_now_add=True)
	updated_at = models.DateTimeField(_('Atualizado em'), auto_now=True)
	loja_codigo = models.CharField(_('Loja'), max_length=10, default='00001')

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['number', 'loja_codigo'], name='uniq_sales_order_number_loja'),
		]
		ordering = ['-created_at']
		verbose_name = _('Pedido')
		verbose_name_plural = _('Pedidos')

	def __str__(self):
		return f'Pedido {self.number}'

	def save(self, *args, **kwargs):
		if not self.number:
			self.number = self._generate_number()
		super().save(*args, **kwargs)

	def _generate_number(self):
		prefix = timezone.now().strftime('PD%y')
		qs = Order.objects.filter(number__startswith=prefix)
		if self.company_id:
			qs = qs.filter(company_id=self.company_id)
		if self.loja_codigo:
			qs = qs.filter(loja_codigo=self.loja_codigo)
		last = qs.order_by('-number').first()
		sequence = 1
		if last:
			try:
				sequence = int(last.number[-4:]) + 1
			except ValueError:
				sequence = 1
		return f'{prefix}{sequence:04d}'

	@property
	def total_amount(self) -> Decimal:
		return sum((item.total_amount for item in self.items.all()), Decimal('0.00'))


class OrderItem(models.Model):
	order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
	product = models.ForeignKey('products.Product', verbose_name=_('Produto'), on_delete=models.PROTECT, blank=True, null=True)
	description = models.CharField(_('Descrição'), max_length=255, blank=True)
	quantity = models.DecimalField(_('Quantidade'), max_digits=10, decimal_places=2, default=Decimal('1.00'))
	unit_price = models.DecimalField(_('Preço unitário'), max_digits=12, decimal_places=2, default=Decimal('0.00'))
	discount = models.DecimalField(_('Desconto'), max_digits=12, decimal_places=2, default=Decimal('0.00'))
	sort_order = models.PositiveIntegerField(_('Ordem'), default=0)
	loja_codigo = models.CharField(_('Loja'), max_length=10, default='00001')

	class Meta:
		ordering = ['sort_order', 'pk']
		verbose_name = _('Item de pedido')
		verbose_name_plural = _('Itens de pedido')

	def __str__(self):
		return self.description or (self.product.name if self.product else 'Item')

	@property
	def total_amount(self) -> Decimal:
		total = (self.quantity or Decimal('0')) * (self.unit_price or Decimal('0'))
		return max(total - (self.discount or Decimal('0')), Decimal('0'))


class Salesperson(models.Model):
	user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name='salesperson_profile', on_delete=models.CASCADE)
	cpf = models.CharField(_('CPF'), max_length=11, unique=True)
	code = models.CharField(_('Código'), max_length=11, unique=True)
	phone = models.CharField(_('Telefone'), max_length=30, blank=True)
	is_active = models.BooleanField(_('Ativo'), default=True)
	created_at = models.DateTimeField(_('Criado em'), auto_now_add=True)
	updated_at = models.DateTimeField(_('Atualizado em'), auto_now=True)

	class Meta:
		verbose_name = _('Vendedor')
		verbose_name_plural = _('Vendedores')
		ordering = ('user__first_name', 'user__last_name', 'user__username')

	def __str__(self):
		nome = self.user.get_full_name() or self.user.get_username()
		return f"{self.code} - {nome}"

	@property
	def formatted_cpf(self) -> str:
		return format_cpf(self.cpf)

	def _sync_cpf(self):
		if not self.cpf:
			raise ValidationError({'cpf': _('Informe o CPF.')})
		try:
			digits = normalize_cpf(self.cpf)
		except ValueError as exc:
			raise ValidationError({'cpf': str(exc)})
		self.cpf = digits
		self.code = digits

	def clean(self):
		super().clean()
		if self.cpf:
			self._sync_cpf()

	def save(self, *args, **kwargs):
		self._sync_cpf()
		super().save(*args, **kwargs)


# -----------------------------------
# Integração de pedidos via API
# -----------------------------------
class Pedido(models.Model):
	class Status(models.TextChoices):
		ORCAMENTO = 'orcamento', _('Orçamento')
		PRE_VENDA = 'pre_venda', _('Pré-venda (Enviada)')
		EM_SEPARACAO = 'em_separacao', _('Pedido em Separação')
		FATURADO = 'faturado', _('Pedido Faturado')
		ENTREGUE = 'entregue', _('Pedido Entregue')
		CANCELADO = 'cancelado', _('Cancelado')

	class PaymentStatus(models.TextChoices):
		AGUARDANDO = 'aguardando', _('Aguardando pagamento')
		PAGO_AVISTA = 'pago_avista', _('Pagamento à vista')
		FATURA_A_VENCER = 'fatura_a_vencer', _('Fatura a vencer')
		NEGADO = 'negado', _('Pagamento negado')

	class FreightMode(models.TextChoices):
		CIF = 'cif', _('CIF')
		FOB = 'fob', _('FOB')
		SEM_FRETE = 'sem_frete', _('Sem frete')

	cliente = models.ForeignKey('clients.Client', on_delete=models.PROTECT, related_name='pedidos_mobile')
	data_criacao = models.DateTimeField()
	total = models.DecimalField(max_digits=10, decimal_places=2)
	data_recebimento = models.DateTimeField(auto_now_add=True)
	status = models.CharField(_('Status'), max_length=20, choices=Status.choices, default=Status.PRE_VENDA)
	pagamento_status = models.CharField(
		_('Status do pagamento'),
		max_length=20,
		choices=PaymentStatus.choices,
		default=PaymentStatus.AGUARDANDO,
	)
	forma_pagamento = models.CharField(_('Forma de pagamento'), max_length=50, blank=True)
	frete_modalidade = models.CharField(
		_('Modalidade de frete'),
		max_length=20,
		choices=FreightMode.choices,
		default=FreightMode.SEM_FRETE,
	)
	loja_codigo = models.CharField(_('Loja'), max_length=10, default='00001')
	vendedor_codigo = models.CharField(_('Código do vendedor'), max_length=50, blank=True)
	vendedor_nome = models.CharField(_('Nome do vendedor'), max_length=150, blank=True)

	class Meta:
		verbose_name = _('Pedido (API)')
		verbose_name_plural = _('Pedidos (API)')

	def __str__(self):
		return f'Pedido API {self.pk} - {self.cliente}'


class ItemPedido(models.Model):
	pedido = models.ForeignKey(Pedido, related_name='itens', on_delete=models.CASCADE)
	produto = models.ForeignKey('products.Product', on_delete=models.PROTECT)
	quantidade = models.DecimalField(max_digits=10, decimal_places=2)
	valor_unitario = models.DecimalField(max_digits=10, decimal_places=2)
	loja_codigo = models.CharField(_('Loja'), max_length=10, default='00001')

	class Meta:
		verbose_name = _('Item do Pedido (API)')
		verbose_name_plural = _('Itens do Pedido (API)')

	def __str__(self):
		return f'{self.quantidade}x {self.produto}'
