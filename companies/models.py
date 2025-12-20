from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from core.utils.documents import normalize_cnpj, format_cnpj


class Company(models.Model):
	class TaxRegime(models.TextChoices):
		SIMPLES = 'simples', 'Simples Nacional'
		PRESUMIDO = 'presumido', 'Lucro Presumido'
		REAL = 'real', 'Lucro Real'
		MEI = 'mei', 'MEI'

	class TaxAgent(models.TextChoices):
		OWN = 'own', 'Próprio'
		THIRD_PARTY = 'third_party', 'Terceirizado'
		JOINT = 'joint', 'Compartilhado'

	code = models.CharField('Código', max_length=14, unique=True)
	name = models.CharField('Razão social', max_length=200)
	trade_name = models.CharField('Nome fantasia', max_length=200, blank=True)
	tax_id = models.CharField('CNPJ', max_length=20, unique=True)
	state_registration = models.CharField('Inscrição estadual', max_length=30, blank=True)
	email = models.EmailField('E-mail', blank=True)
	phone = models.CharField('Telefone', max_length=30, blank=True)
	website = models.URLField('Website', blank=True)
	address = models.CharField('Endereço', max_length=255, blank=True)
	number = models.CharField('Número', max_length=20, blank=True)
	complement = models.CharField('Complemento', max_length=100, blank=True)
	district = models.CharField('Bairro', max_length=100, blank=True)
	city = models.CharField('Cidade', max_length=100, blank=True)
	state = models.CharField('UF', max_length=2, blank=True)
	zip_code = models.CharField('CEP', max_length=12, blank=True)
	tax_regime = models.CharField('Regime tributário', max_length=30, choices=TaxRegime.choices, default=TaxRegime.SIMPLES)
	tax_agent = models.CharField('Agente tributário', max_length=30, choices=TaxAgent.choices, default=TaxAgent.OWN)
	default_discount_percent = models.DecimalField('Desconto padrão (%)', max_digits=5, decimal_places=2, default=Decimal('0.00'))
	max_discount_percent = models.DecimalField('Desconto máximo (%)', max_digits=5, decimal_places=2, default=Decimal('0.00'))
	notes = models.TextField('Observações', blank=True)
	is_active = models.BooleanField('Ativa', default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		verbose_name = 'Empresa'
		verbose_name_plural = 'Empresas'
		ordering = ['name']

	def __str__(self):
		display_name = self.trade_name or self.name
		return f"{self.code} - {display_name}" if self.code else display_name

	def _sync_identifiers(self):
		if not self.tax_id:
			raise ValidationError({'tax_id': 'Informe o CNPJ.'})
		try:
			cnpj_digits = normalize_cnpj(self.tax_id)
		except ValueError as exc:
			raise ValidationError({'tax_id': str(exc)})
		self.code = cnpj_digits
		self.tax_id = format_cnpj(cnpj_digits)

	def clean(self):
		super().clean()
		if self.tax_id:
			self._sync_identifiers()
		if self.default_discount_percent < 0:
			raise ValidationError({'default_discount_percent': 'Informe um percentual positivo.'})
		if self.max_discount_percent < 0:
			raise ValidationError({'max_discount_percent': 'Informe um percentual positivo.'})
		if self.max_discount_percent and self.default_discount_percent > self.max_discount_percent:
			raise ValidationError({'default_discount_percent': 'O desconto padrão deve ser menor ou igual ao máximo permitido.'})

	def save(self, *args, **kwargs):
		self._sync_identifiers()
		super().save(*args, **kwargs)

# Create your models here.
