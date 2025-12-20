from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.utils.certificates import CertificateError, load_pkcs12_from_bytes


class SefazConfiguration(models.Model):
	class Environment(models.TextChoices):
		PRODUCTION = 'production', 'Produção'
		HOMOLOGATION = 'homologation', 'Homologação'

	base_url = models.URLField('URL base da SEFAZ', blank=True)
	token = models.CharField('Token de acesso', max_length=255, blank=True)
	timeout = models.PositiveIntegerField('Timeout (segundos)', default=10)
	environment = models.CharField(
		'Ambiente SEFAZ',
		max_length=20,
		choices=Environment.choices,
		default=Environment.PRODUCTION,
	)
	certificate_file = models.FileField(
		'Certificado digital A1 (PFX/P12)',
		upload_to='certificates',
		blank=True,
		null=True,
	)
	certificate_password = models.CharField('Senha do certificado', max_length=255, blank=True)
	certificate_uploaded_at = models.DateTimeField('Certificado enviado em', null=True, blank=True)
	certificate_subject = models.CharField('Proprietário do certificado', max_length=255, blank=True)
	certificate_serial_number = models.CharField('Número de série', max_length=120, blank=True)
	certificate_valid_from = models.DateTimeField('Certificado válido a partir de', null=True, blank=True)
	certificate_valid_until = models.DateTimeField('Certificado válido até', null=True, blank=True)
	updated_at = models.DateTimeField('Atualizado em', auto_now=True)
	updated_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		verbose_name='Atualizado por',
	)

	CACHE_KEY = 'core.sefaz-config'

	class Meta:
		verbose_name = 'Configuração SEFAZ'
		verbose_name_plural = 'Configuração SEFAZ'

	def __str__(self):
		return 'Configuração SEFAZ'

	@classmethod
	def load(cls):
		cached = cache.get(cls.CACHE_KEY)
		if cached and getattr(cached, 'pk', None) and cls.objects.filter(pk=cached.pk).exists():
			return cached
		instance = cls.objects.first()
		if not instance:
			instance = cls.objects.create()
		cache.set(cls.CACHE_KEY, instance, 300)
		return instance

	@classmethod
	def clear_cache(cls):
		cache.delete(cls.CACHE_KEY)

	def save(self, *args, **kwargs):
		original = None
		if self.pk:
			try:
				original = SefazConfiguration.objects.get(pk=self.pk)
			except SefazConfiguration.DoesNotExist:
				original = None

		current_file_name = getattr(self.certificate_file, 'name', None)
		original_file_name = getattr(original.certificate_file, 'name', None) if original and original.certificate_file else None

		file_cleared = original_file_name and not self.certificate_file
		file_changed = (
			self.certificate_file
			and (
				not original_file_name
				or original_file_name != current_file_name
			)
		)

		if file_changed:
			self.certificate_uploaded_at = timezone.now()

		if file_changed and self.certificate_file and not self.certificate_password:
			raise ValidationError({'certificate_password': 'Informe a senha do certificado para validar o arquivo.'})

		certificate_bundle = None
		if file_changed and self.certificate_file and self.certificate_password:
			file_was_opened = False
			try:
				if not getattr(self.certificate_file, 'file', None):
					self.certificate_file.open('rb')
					file_was_opened = True
				data = self.certificate_file.read()
				if hasattr(self.certificate_file, 'seek'):
					self.certificate_file.seek(0)
				certificate_bundle = load_pkcs12_from_bytes(data, self.certificate_password)
			except CertificateError as exc:
				raise ValidationError({'certificate_file': str(exc)})
			except Exception as exc:
				raise ValidationError({'certificate_file': 'Falha ao processar o certificado digital.'}) from exc
			finally:
				if file_was_opened:
					try:
						self.certificate_file.close()
					except Exception:
						pass
			if certificate_bundle:
				meta = certificate_bundle.metadata
				self.certificate_subject = meta.subject
				self.certificate_serial_number = meta.serial_number
				self.certificate_valid_from = meta.valid_from
				self.certificate_valid_until = meta.valid_until

		if file_cleared:
			original.certificate_file.delete(save=False)
			self.certificate_subject = ''
			self.certificate_serial_number = ''
			self.certificate_valid_from = None
			self.certificate_valid_until = None
			self.certificate_uploaded_at = None

		if file_changed and original_file_name:
			original.certificate_file.delete(save=False)

		super().save(*args, **kwargs)
		cache.set(self.CACHE_KEY, self, 300)

	def delete(self, *args, **kwargs):
		if self.certificate_file:
			self.certificate_file.delete(save=False)
		super().delete(*args, **kwargs)
		self.clear_cache()


class EmailConfiguration(models.Model):
	smtp_host = models.CharField('Servidor SMTP', max_length=255, blank=True)
	smtp_port = models.PositiveIntegerField('Porta SMTP', default=587)
	smtp_username = models.CharField('Usuário SMTP', max_length=255, blank=True)
	smtp_password = models.CharField('Senha SMTP', max_length=255, blank=True)
	smtp_use_tls = models.BooleanField('SMTP com STARTTLS', default=True)
	smtp_use_ssl = models.BooleanField('SMTP com SSL', default=False)
	default_from_email = models.EmailField('Remetente padrão', blank=True)
	incoming_protocol = models.CharField(
		'Protocolo de recebimento',
		max_length=10,
		choices=(
			('imap', 'IMAP'),
			('pop3', 'POP3'),
		),
		default='imap',
	)
	incoming_host = models.CharField('Servidor de entrada', max_length=255, blank=True)
	incoming_port = models.PositiveIntegerField('Porta de entrada', default=993)
	incoming_username = models.CharField('Usuário de entrada', max_length=255, blank=True)
	incoming_password = models.CharField('Senha de entrada', max_length=255, blank=True)
	incoming_use_ssl = models.BooleanField('Recebimento com SSL/TLS', default=True)
	incoming_use_tls = models.BooleanField('Recebimento com STARTTLS', default=False)
	updated_at = models.DateTimeField('Atualizado em', auto_now=True)
	updated_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		verbose_name='Atualizado por',
	)

	CACHE_KEY = 'core.email-config'

	class Meta:
		verbose_name = 'Configuração de e-mail'
		verbose_name_plural = 'Configurações de e-mail'

	def __str__(self):
		return 'Configurações de e-mail'

	@classmethod
	def load(cls):
		cached = cache.get(cls.CACHE_KEY)
		if cached and getattr(cached, 'pk', None) and cls.objects.filter(pk=cached.pk).exists():
			return cached
		instance = cls.objects.first()
		if not instance:
			instance = cls.objects.create()
		cache.set(cls.CACHE_KEY, instance, 300)
		return instance

	@classmethod
	def clear_cache(cls):
		cache.delete(cls.CACHE_KEY)

	def save(self, *args, **kwargs):
		super().save(*args, **kwargs)
		cache.set(self.CACHE_KEY, self, 300)

	def delete(self, *args, **kwargs):
		super().delete(*args, **kwargs)
		self.clear_cache()


class SalesConfiguration(models.Model):
	default_quote_validity_days = models.PositiveIntegerField('Validade padrão do orçamento (dias)', default=7)
	updated_at = models.DateTimeField('Atualizado em', auto_now=True)
	updated_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		verbose_name='Atualizado por',
	)

	CACHE_KEY = 'core.sales-config'

	class Meta:
		verbose_name = 'Configuração de vendas'
		verbose_name_plural = 'Configurações de vendas'

	def __str__(self):
		return 'Configurações de vendas'

	@classmethod
	def load(cls):
		cached = cache.get(cls.CACHE_KEY)
		if cached and getattr(cached, 'pk', None) and cls.objects.filter(pk=cached.pk).exists():
			return cached
		instance = cls.objects.first()
		if not instance:
			instance = cls.objects.create()
		cache.set(cls.CACHE_KEY, instance, 300)
		return instance

	@classmethod
	def clear_cache(cls):
		cache.delete(cls.CACHE_KEY)

	def save(self, *args, **kwargs):
		super().save(*args, **kwargs)
		cache.set(self.CACHE_KEY, self, 300)

	def delete(self, *args, **kwargs):
		super().delete(*args, **kwargs)
		self.clear_cache()


class UserRole(models.Model):
	code = models.SlugField('Código', unique=True)
	name = models.CharField('Nome da função', max_length=120, unique=True)
	description = models.CharField('Descrição', max_length=255, blank=True)
	created_at = models.DateTimeField('Criado em', auto_now_add=True)

	class Meta:
		verbose_name = 'Função de usuário'
		verbose_name_plural = 'Funções de usuário'
		ordering = ('name',)

	def __str__(self):
		return self.name


class UserAccessProfile(models.Model):
	user = models.OneToOneField(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name='access_profile',
		verbose_name='Usuário',
	)
	companies = models.ManyToManyField(
		'companies.Company',
		blank=True,
		related_name='access_profiles',
		verbose_name='Empresas permitidas',
	)
	roles = models.ManyToManyField(
		UserRole,
		blank=True,
		related_name='profiles',
		verbose_name='Funções atribuídas',
	)
	can_view_all_companies = models.BooleanField('Visualiza todas as empresas', default=False)
	can_manage_products = models.BooleanField('Produtos', default=True)
	can_manage_clients = models.BooleanField('Clientes', default=True)
	can_manage_sales = models.BooleanField('Vendas', default=True)
	can_manage_purchases = models.BooleanField('Compras', default=True)
	can_manage_finance = models.BooleanField('Financeiro', default=True)
	can_create_sales_records = models.BooleanField('Criar vendas e orçamentos', default=True)
	can_edit_sales_records = models.BooleanField('Editar vendas e orçamentos', default=True)
	can_delete_sales_records = models.BooleanField('Excluir vendas e orçamentos', default=True)
	display_name = models.CharField('Nome para exibição', max_length=120, blank=True)
	avatar = models.ImageField('Foto do perfil', upload_to='avatars/', blank=True, null=True)
	interface_font_size = models.CharField(
		'Tamanho da fonte',
		max_length=20,
		choices=(
			('small', 'Pequeno'),
			('medium', 'Médio'),
			('large', 'Grande'),
		),
		default='medium',
	)
	notes = models.TextField('Observações internas', blank=True)
	updated_at = models.DateTimeField('Atualizado em', auto_now=True)
	updated_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name='+',
		verbose_name='Atualizado por',
	)

	class Meta:
		verbose_name = 'Perfil de acesso'
		verbose_name_plural = 'Perfis de acesso'
		ordering = ('user__username',)

	def __str__(self):
		return f'Permissões de {self.user.get_full_name() or self.user.username}'

	def allowed_modules(self):
		return {
			'products': self.can_manage_products,
			'clients': self.can_manage_clients,
			'sales': self.can_manage_sales,
			'purchases': self.can_manage_purchases,
			'finance': self.can_manage_finance,
		}

	def sales_permissions(self):
		"""Return granular permissions for sales-related actions."""
		if not self.can_manage_sales:
			return {
				'manage': False,
				'create': False,
				'edit': False,
				'delete': False,
			}
		return {
			'manage': True,
			'create': self.can_create_sales_records,
			'edit': self.can_edit_sales_records,
			'delete': self.can_delete_sales_records,
		}

	def companies_names(self):
		return ', '.join(c.trade_name or c.name for c in self.companies.all())

	def roles_names(self):
		return ', '.join(role.name for role in self.roles.all())
