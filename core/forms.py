from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from companies.models import Company
from core.utils.certificates import CertificateError, CertificateBundle, load_pkcs12_from_bytes

from .models import EmailConfiguration, SefazConfiguration, SalesConfiguration, UserAccessProfile, UserRole


class SefazConfigurationForm(forms.ModelForm):
	certificate_file = forms.FileField(
		label='Certificado digital A1 (arquivo .pfx ou .p12)',
		required=False,
		allow_empty_file=False,
		widget=forms.FileInput(attrs={'class': 'file-input', 'accept': '.pfx,.p12'}),
		help_text='Envie o arquivo do certificado emitido pela autoridade certificadora.',
	)
	certificate_password = forms.CharField(
		label='Senha do certificado',
		required=False,
		widget=forms.PasswordInput(attrs={'class': 'input', 'autocomplete': 'new-password'}),
		help_text='Obrigatória ao enviar um novo certificado.',
	)
	clear_certificate = forms.BooleanField(
		label='Remover certificado atual',
		required=False,
		widget=forms.CheckboxInput(attrs={'class': 'checkbox'}),
	)

	class Meta:
		model = SefazConfiguration
		fields = ['base_url', 'token', 'timeout', 'environment']
		labels = {
			'base_url': 'URL base da API SEFAZ',
			'token': 'Token de autenticação',
			'timeout': 'Timeout (segundos)',
			'environment': 'Ambiente para consultas',
		}
		widgets = {
			'base_url': forms.URLInput(attrs={'class': 'input', 'placeholder': 'https://sefaz.exemplo.gov.br/api'}),
			'token': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Opcional'}),
			'timeout': forms.NumberInput(attrs={'class': 'input', 'min': 1}),
			'environment': forms.Select(attrs={'class': 'select'}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['certificate_password'].widget.attrs.setdefault('placeholder', 'Senha do arquivo (.pfx/.p12)')
		self.has_certificate = bool(self.instance and self.instance.certificate_file)
		if self.has_certificate:
			self.fields['certificate_file'].help_text = 'Envie um novo arquivo para substituir o certificado atual.'
		self._pending_certificate_bundle: CertificateBundle | None = None

	def clean_timeout(self):
		timeout = self.cleaned_data.get('timeout') or 10
		if timeout <= 0:
			raise forms.ValidationError('Informe um timeout maior que zero.')
		return timeout

	def clean_certificate_file(self):
		file_obj = self.cleaned_data.get('certificate_file')
		if not file_obj:
			return file_obj
		if file_obj.size > 5 * 1024 * 1024:
			raise forms.ValidationError('O certificado deve ter até 5 MB.')
		filename = (file_obj.name or '').lower()
		if not filename.endswith(('.pfx', '.p12')):
			raise forms.ValidationError('Envie um arquivo com extensão .pfx ou .p12.')
		return file_obj

	def clean(self):
		cleaned_data = super().clean()
		cert_file = cleaned_data.get('certificate_file')
		password = (cleaned_data.get('certificate_password') or '').strip()
		clear = cleaned_data.get('clear_certificate')

		if clear and cert_file:
			self.add_error('clear_certificate', 'Não é possível remover e substituir o certificado na mesma operação.')
		if cert_file and not password:
			self.add_error('certificate_password', 'Informe a senha do certificado para validar o arquivo.')
		if clear and not (self.instance and self.instance.certificate_file):
			self.add_error('clear_certificate', 'Nenhum certificado cadastrado para remoção.')

		if cert_file and password and not self.errors.get('certificate_file') and not self.errors.get('certificate_password'):
			uploaded_bytes = cert_file.read()
			cert_file.seek(0)
			try:
				self._pending_certificate_bundle = load_pkcs12_from_bytes(uploaded_bytes, password)
			except CertificateError as exc:
				self.add_error('certificate_file', str(exc))
				self._pending_certificate_bundle = None
		elif password and not cert_file and self.instance and self.instance.certificate_file and not self.errors.get('certificate_password'):
			file_field = self.instance.certificate_file
			try:
				file_field.open('rb')
				existing_bytes = file_field.read()
			except FileNotFoundError:
				self.add_error('certificate_password', 'Arquivo do certificado atual não foi encontrado.')
				existing_bytes = None
			finally:
				try:
					file_field.close()
				except Exception:
					pass
			if existing_bytes:
				try:
					load_pkcs12_from_bytes(existing_bytes, password)
				except CertificateError as exc:
					self.add_error('certificate_password', str(exc))
		return cleaned_data

	def save(self, commit=True):
		instance = super().save(commit=False)
		cert_file = self.cleaned_data.get('certificate_file')
		password = (self.cleaned_data.get('certificate_password') or '').strip()
		clear = self.cleaned_data.get('clear_certificate')

		if clear:
			instance.certificate_file = None
			instance.certificate_password = ''
			instance.certificate_subject = ''
			instance.certificate_serial_number = ''
			instance.certificate_valid_from = None
			instance.certificate_valid_until = None
			instance.certificate_uploaded_at = None
		else:
			if cert_file:
				instance.certificate_file = cert_file
				if self._pending_certificate_bundle:
					meta = self._pending_certificate_bundle.metadata
					instance.certificate_subject = meta.subject
					instance.certificate_serial_number = meta.serial_number
					instance.certificate_valid_from = meta.valid_from
					instance.certificate_valid_until = meta.valid_until
			if password:
				instance.certificate_password = password

		if commit:
			instance.save()
		return instance


class EmailConfigurationForm(forms.ModelForm):
	class Meta:
		model = EmailConfiguration
		fields = [
			'smtp_host',
			'smtp_port',
			'smtp_username',
			'smtp_password',
			'smtp_use_tls',
			'smtp_use_ssl',
			'default_from_email',
			'incoming_protocol',
			'incoming_host',
			'incoming_port',
			'incoming_username',
			'incoming_password',
			'incoming_use_ssl',
			'incoming_use_tls',
		]
		labels = {
			'smtp_host': 'Servidor SMTP',
			'smtp_port': 'Porta SMTP',
			'smtp_username': 'Usuário SMTP',
			'smtp_password': 'Senha SMTP',
			'smtp_use_tls': 'Usar STARTTLS (TLS)',
			'smtp_use_ssl': 'Usar SSL (porta dedicada)',
			'default_from_email': 'Remetente padrão',
			'incoming_protocol': 'Protocolo de recebimento',
			'incoming_host': 'Servidor de entrada',
			'incoming_port': 'Porta de entrada',
			'incoming_username': 'Usuário de entrada',
			'incoming_password': 'Senha de entrada',
			'incoming_use_ssl': 'Receber com SSL/TLS',
			'incoming_use_tls': 'Receber com STARTTLS',
		}
		widgets = {
			'smtp_host': forms.TextInput(attrs={'class': 'input', 'placeholder': 'smtp.seudominio.com'}),
			'smtp_port': forms.NumberInput(attrs={'class': 'input', 'min': 1}),
			'smtp_username': forms.TextInput(attrs={'class': 'input'}),
			'smtp_password': forms.PasswordInput(attrs={'class': 'input', 'render_value': True}),
			'default_from_email': forms.EmailInput(attrs={'class': 'input', 'placeholder': 'noreply@seudominio.com'}),
			'incoming_protocol': forms.Select(attrs={'class': 'select'}),
			'incoming_host': forms.TextInput(attrs={'class': 'input', 'placeholder': 'imap.seudominio.com'}),
			'incoming_port': forms.NumberInput(attrs={'class': 'input', 'min': 1}),
			'incoming_username': forms.TextInput(attrs={'class': 'input'}),
			'incoming_password': forms.PasswordInput(attrs={'class': 'input', 'render_value': True}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		for field in ('smtp_use_tls', 'smtp_use_ssl', 'incoming_use_ssl', 'incoming_use_tls'):
			self.fields[field].widget.attrs.setdefault('class', 'checkbox')

	def clean_smtp_port(self):
		port = self.cleaned_data.get('smtp_port') or 0
		if port <= 0:
			raise forms.ValidationError('Informe uma porta SMTP válida.')
		return port

	def clean_incoming_port(self):
		port = self.cleaned_data.get('incoming_port') or 0
		if port <= 0:
			raise forms.ValidationError('Informe uma porta de entrada válida.')
		return port

	def clean(self):
		cleaned_data = super().clean()
		if cleaned_data.get('smtp_use_tls') and cleaned_data.get('smtp_use_ssl'):
			msg = 'Selecione apenas uma opção de criptografia para envio.'
			self.add_error('smtp_use_tls', msg)
			self.add_error('smtp_use_ssl', msg)
		if cleaned_data.get('incoming_use_tls') and cleaned_data.get('incoming_use_ssl'):
			msg = 'Selecione apenas uma opção de criptografia para recebimento.'
			self.add_error('incoming_use_tls', msg)
			self.add_error('incoming_use_ssl', msg)
		return cleaned_data


class SalesConfigurationForm(forms.ModelForm):
	class Meta:
		model = SalesConfiguration
		fields = ['default_quote_validity_days']
		labels = {
			'default_quote_validity_days': 'Validade padrão dos orçamentos (em dias)',
		}
		widgets = {
			'default_quote_validity_days': forms.NumberInput(attrs={'class': 'input', 'min': 0}),
		}

	def clean_default_quote_validity_days(self):
		value = self.cleaned_data.get('default_quote_validity_days')
		if value is None:
			return 0
		if value < 0:
			raise forms.ValidationError('Informe um número de dias maior ou igual a zero.')
		return value


class EmailTestForm(forms.Form):
	recipient = forms.EmailField(
		label='Destinatário de teste',
		help_text='Informe o e-mail que receberá a mensagem de teste.',
		widget=forms.EmailInput(attrs={'class': 'input', 'placeholder': 'contato@seudominio.com'}),
	)


class UserProfileForm(forms.ModelForm):
	full_name = forms.CharField(
		label='Seu nome completo',
		required=False,
		max_length=150,
		widget=forms.TextInput(attrs={'class': 'input', 'placeholder': 'Como deseja ser chamado(a)?'}),
	)

	class Meta:
		model = get_user_model()
		fields = ['email']
		labels = {'email': 'Seu e-mail'}
		widgets = {
			'email': forms.EmailInput(attrs={'class': 'input', 'placeholder': 'voce@empresa.com.br'}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		full_name = ''
		if getattr(self, 'instance', None):
			full_name = self.instance.get_full_name().strip()
		if not full_name and getattr(self, 'instance', None):
			full_name = self.instance.username
		self.fields['full_name'].initial = full_name

	def save(self, commit=True):
		user = super().save(commit=False)
		full_name = self.cleaned_data.get('full_name', '').strip()
		first_name = ''
		last_name = ''
		if full_name:
			parts = [part for part in full_name.split() if part]
			if parts:
				first_name = parts[0]
				if len(parts) > 1:
					last_name = ' '.join(parts[1:])
		user.first_name = first_name
		user.last_name = last_name
		if commit:
			user.save()
		return user


class UserPreferencesForm(forms.ModelForm):
	remove_avatar = forms.BooleanField(
		required=False,
		label='Remover foto atual',
		widget=forms.CheckboxInput(attrs={'class': 'checkbox'}),
	)

	class Meta:
		model = UserAccessProfile
		fields = ['display_name', 'avatar', 'interface_font_size']
		labels = {
			'display_name': 'Nome para exibição',
			'avatar': 'Foto do perfil',
			'interface_font_size': 'Tamanho da fonte',
		}
		widgets = {
			'display_name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Ex.: Andre Silva'}),
			'interface_font_size': forms.Select(attrs={'class': 'is-fullwidth'}),
			'avatar': forms.FileInput(attrs={'accept': 'image/*', 'class': 'file-input', 'style': 'display:none;'}),
		}

	def save(self, commit=True):
		instance = super().save(commit=False)
		if self.cleaned_data.get('remove_avatar'):
			instance.avatar = None
		if commit:
			instance.save()
		return instance

	def clean(self):
		cleaned_data = super().clean()
		if cleaned_data.get('avatar') and cleaned_data.get('remove_avatar'):
			cleaned_data['remove_avatar'] = False
		return cleaned_data

class UserAccessProfileForm(forms.ModelForm):
	companies = forms.ModelMultipleChoiceField(
		queryset=Company.objects.all().order_by('trade_name', 'name'),
		required=False,
		widget=forms.SelectMultiple(attrs={'class': 'select is-multiple', 'size': '6'}),
		label='Empresas permitidas',
	)
	roles = forms.ModelMultipleChoiceField(
		queryset=UserRole.objects.all().order_by('name'),
		required=False,
		widget=forms.SelectMultiple(attrs={'class': 'select is-multiple', 'size': '6'}),
		label='Funções do usuário',
		help_text='Selecione as funções/desempenhos atribuídos ao colaborador.',
	)

	class Meta:
		model = UserAccessProfile
		fields = [
			'roles',
			'can_view_all_companies',
			'can_manage_products',
			'can_manage_clients',
			'can_manage_sales',
			'can_manage_purchases',
			'can_manage_finance',
			'can_create_sales_records',
			'can_edit_sales_records',
			'can_delete_sales_records',
			'companies',
			'notes',
		]
		labels = {
			'can_manage_products': 'Acessa Produtos',
			'can_manage_clients': 'Acessa Clientes',
			'can_manage_sales': 'Acessa Vendas',
			'can_manage_purchases': 'Acessa Compras',
			'can_manage_finance': 'Acessa Financeiro',
			'can_create_sales_records': 'Pode criar orçamentos / pedidos',
			'can_edit_sales_records': 'Pode editar orçamentos / pedidos',
			'can_delete_sales_records': 'Pode excluir orçamentos / pedidos',
			'can_view_all_companies': 'Visualiza todas as empresas',
			'notes': 'Observações',
		}
		widgets = {
			'notes': forms.Textarea(attrs={'class': 'textarea', 'rows': 3, 'placeholder': 'Instruções internas, exceções etc.'}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['companies'].queryset = Company.objects.all().order_by('trade_name', 'name')
		self.fields['roles'].queryset = UserRole.objects.all().order_by('name')
		for field in [
			'can_view_all_companies',
			'can_manage_products',
			'can_manage_clients',
			'can_manage_sales',
			'can_manage_purchases',
			'can_manage_finance',
			'can_create_sales_records',
			'can_edit_sales_records',
			'can_delete_sales_records',
		]:
			self.fields[field].widget.attrs.setdefault('class', 'checkbox')


class UserCreateForm(UserCreationForm):
	first_name = forms.CharField(
		label='Nome',
		max_length=150,
		required=False,
		widget=forms.TextInput(attrs={'class': 'input'}),
	)
	last_name = forms.CharField(
		label='Sobrenome',
		max_length=150,
		required=False,
		widget=forms.TextInput(attrs={'class': 'input'}),
	)
	email = forms.EmailField(
		label='E-mail',
		required=False,
		widget=forms.EmailInput(attrs={'class': 'input'}),
	)
	is_active = forms.BooleanField(
		label='Usuário ativo',
		initial=True,
		required=False,
		widget=forms.CheckboxInput(attrs={'class': 'checkbox'}),
	)

	class Meta(UserCreationForm.Meta):
		model = get_user_model()
		fields = ('username', 'first_name', 'last_name', 'email', 'is_active')

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['username'].widget.attrs.setdefault('class', 'input')
		self.fields['password1'].widget.attrs.setdefault('class', 'input')
		self.fields['password2'].widget.attrs.setdefault('class', 'input')

	def save(self, commit=True):
		user = super().save(commit=False)
		user.is_active = self.cleaned_data.get('is_active', True)
		if commit:
			user.save()
		return user


class ApiUserTokenForm(forms.Form):
	username = forms.CharField(
		label='Usuário da API',
		max_length=150,
		widget=forms.TextInput(attrs={'class': 'input', 'autocomplete': 'off'}),
	)
	password = forms.CharField(
		label='Senha',
		required=False,
		widget=forms.PasswordInput(attrs={'class': 'input', 'autocomplete': 'new-password'}),
	)
	vendor_code = forms.CharField(
		label='Código do vendedor (opcional)',
		max_length=50,
		required=False,
		widget=forms.TextInput(attrs={'class': 'input'}),
	)
	is_active = forms.BooleanField(
		label='Usuário ativo',
		required=False,
		initial=True,
		widget=forms.CheckboxInput(attrs={'class': 'checkbox'}),
	)
