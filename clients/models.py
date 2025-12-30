from django.core.exceptions import ValidationError
from django.db import models

from core.utils.documents import (
	format_cnpj,
	format_cpf,
	normalize_cnpj,
	normalize_cpf,
)


class Client(models.Model):
	class PersonType(models.TextChoices):
		INDIVIDUAL = 'F', 'Pessoa Física'
		LEGAL = 'J', 'Pessoa Jurídica'

	person_type = models.CharField('Tipo de pessoa', max_length=1, choices=PersonType.choices, default=PersonType.INDIVIDUAL)
	code = models.CharField('Código', max_length=14, unique=True)
	document = models.CharField('CPF/CNPJ', max_length=14, unique=True)
	first_name = models.CharField('Nome / Razão social', max_length=150)
	last_name = models.CharField('Sobrenome / Nome fantasia', max_length=150, blank=True)
	email = models.EmailField('E-mail', unique=True)
	phone = models.CharField('Telefone', max_length=30, blank=True)
	state_registration = models.CharField('Inscrição estadual', max_length=30, blank=True)
	address = models.CharField('Endereço', max_length=255, blank=True)
	number = models.CharField('Número', max_length=20, blank=True)
	complement = models.CharField('Complemento', max_length=100, blank=True)
	district = models.CharField('Bairro', max_length=100, blank=True)
	city = models.CharField('Cidade', max_length=100, blank=True)
	state = models.CharField('UF', max_length=2, blank=True)
	zip_code = models.CharField('CEP', max_length=12, blank=True)
	created_at = models.DateTimeField('Criado em', auto_now_add=True)
	updated_at = models.DateTimeField('Atualizado em', auto_now=True)

	class Meta:
		ordering = ('first_name', 'last_name')
		verbose_name = 'Cliente'
		verbose_name_plural = 'Clientes'

	def __str__(self):
		display_name = f"{self.first_name} {self.last_name}".strip()
		return f"{self.code} - {display_name or self.email}"

	@property
	def formatted_document(self) -> str:
		if not self.document:
			return ''
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

	@classmethod
	def get_default_consumer(cls):
		"""Return (or create) the fallback client used when none is selected."""
		defaults = {
			'person_type': cls.PersonType.INDIVIDUAL,
			'first_name': 'Consumidor',
			'last_name': 'Final',
			'email': 'consumidor-final@example.com',
		}
		client, _ = cls.objects.get_or_create(document='00000000000', defaults=defaults)
		return client


class ClienteSync(models.Model):
	"""Staging de clientes vindos da integração (ERP externo)."""

	cliente_codigo = models.CharField(max_length=50, primary_key=True)
	cliente_status = models.IntegerField(null=True, blank=True)
	cliente_razao_social = models.CharField(max_length=255, null=True, blank=True)
	cliente_nome_fantasia = models.CharField(max_length=255, null=True, blank=True)
	cliente_cnpj_cpf = models.CharField(max_length=32, null=True, blank=True)
	cliente_tipo_pf_pj = models.CharField(max_length=4, null=True, blank=True)
	cliente_endereco = models.CharField(max_length=255, null=True, blank=True)
	cliente_numero = models.CharField(max_length=50, null=True, blank=True)
	cliente_bairro = models.CharField(max_length=255, null=True, blank=True)
	cliente_cidade = models.CharField(max_length=255, null=True, blank=True)
	cliente_uf = models.CharField(max_length=5, null=True, blank=True)
	cliente_cep = models.CharField(max_length=20, null=True, blank=True)
	cliente_telefone1 = models.CharField(max_length=50, null=True, blank=True)
	cliente_telefone2 = models.CharField(max_length=50, null=True, blank=True)
	cliente_email = models.CharField(max_length=255, null=True, blank=True)
	cliente_inscricao_municipal = models.CharField(max_length=50, null=True, blank=True)
	vendedor_codigo = models.CharField(max_length=50, null=True, blank=True)
	vendedor_nome = models.CharField(max_length=255, null=True, blank=True)
	ultima_venda_data = models.DateTimeField(null=True, blank=True)
	ultima_venda_valor = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
	loja_codigo = models.CharField(max_length=10, null=True, blank=True)
	updated_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		managed = False
		db_table = 'erp_clientes_vendedores_view'
		ordering = ('cliente_razao_social', 'cliente_codigo')

	def __str__(self) -> str:
		nome = self.cliente_nome_fantasia or self.cliente_razao_social or ''
		return f'{self.cliente_codigo} - {nome}'
