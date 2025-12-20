from decimal import Decimal

from datetime import timedelta

from django import forms
from django.forms import inlineformset_factory
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Q

from clients.models import Client
from core.utils.documents import normalize_cpf, format_cpf
from core.models import SalesConfiguration
from .models import Quote, QuoteItem, Order, OrderItem, Salesperson


class QuoteForm(forms.ModelForm):
	class Meta:
		model = Quote
		fields = ['client', 'salesperson', 'valid_until', 'status', 'notes']
		widgets = {
			'valid_until': forms.DateInput(attrs={'type': 'date'}),
			'notes': forms.Textarea(attrs={'rows': 3}),
			'salesperson': forms.Select(attrs={'class': 'select'}),
		}

	def __init__(self, *args, **kwargs):
		user = kwargs.pop('user', None)
		super().__init__(*args, **kwargs)
		self.fields['client'].required = False
		self._default_client = Client.get_default_consumer()
		self.fields['client'].empty_label = 'Consumidor final (padrão)'
		self.fields['client'].widget.attrs.setdefault('class', 'select')
		self.fields['client'].widget.attrs['data-lookup-type'] = 'clients'
		self.fields['client'].widget.attrs.setdefault('data-lookup-placeholder', 'Buscar clientes (F2)')
		salesperson_qs = Salesperson.objects.select_related('user').order_by('user__first_name', 'user__last_name', 'user__username')
		if self.instance and self.instance.pk and self.instance.salesperson_id:
			salesperson_qs = salesperson_qs.filter(Q(is_active=True) | Q(pk=self.instance.salesperson_id))
		else:
			salesperson_qs = salesperson_qs.filter(is_active=True)
		self.fields['salesperson'].queryset = salesperson_qs
		self.fields['salesperson'].label = 'Vendedor'
		self.fields['salesperson'].empty_label = 'Selecione um vendedor'
		self.fields['salesperson'].required = True
		if not salesperson_qs.exists():
			self.fields['salesperson'].required = False
			self.fields['salesperson'].empty_label = 'Cadastre um vendedor ativo'
		if not self.data and not self.instance.pk and self._default_client:
			self.initial.setdefault('client', self._default_client.pk)
			self.fields['client'].initial = self._default_client.pk
		if not self.data and not self.instance.pk and user:
			sales_profile = getattr(user, 'salesperson_profile', None)
			if sales_profile and sales_profile.is_active:
				self.initial.setdefault('salesperson', sales_profile.pk)
				self.fields['salesperson'].initial = sales_profile.pk
		config = SalesConfiguration.load()
		if not self.data and not self.instance.pk:
			days = getattr(config, 'default_quote_validity_days', 0) or 0
			if days > 0:
				default_valid_until = timezone.localdate() + timedelta(days=days)
				self.initial.setdefault('valid_until', default_valid_until)
				self.fields['valid_until'].initial = default_valid_until

	def clean_client(self):
		client = self.cleaned_data.get('client')
		if client:
			return client
		return self._default_client or Client.get_default_consumer()


class QuoteItemForm(forms.ModelForm):
	class Meta:
		model = QuoteItem
		fields = ['product', 'description', 'quantity', 'unit_price', 'discount', 'delivery_days', 'sort_order']
		widgets = {
			'product': forms.Select(attrs={
				'class': 'select product-select visually-hidden',
				'data-product-select': 'true',
				'tabindex': '-1',
			}),
			'description': forms.HiddenInput(attrs={'data-description-field': 'true'}),
			'quantity': forms.NumberInput(attrs={'step': '0.01', 'data-field': 'quantity', 'class': 'input'}),
			'unit_price': forms.NumberInput(attrs={'step': '0.01', 'data-field': 'unit_price', 'class': 'input'}),
			'delivery_days': forms.NumberInput(attrs={'min': 0, 'step': 1, 'class': 'input', 'placeholder': 'Ex.: 5'}),
			'discount': forms.NumberInput(attrs={
				'step': '0.01',
				'data-field': 'discount',
				'data-discount-field': 'true',
				'class': 'input discount-field',
				'readonly': 'readonly',
				'tabindex': '-1',
				'aria-disabled': 'true',
			}),
			'sort_order': forms.NumberInput(attrs={'min': 0}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['discount'].required = False

	def clean_discount(self):
		value = self.cleaned_data.get('discount')
		if value in (None, ''):
			return Decimal('0')
		return value


QuoteItemFormSet = inlineformset_factory(
	Quote,
	QuoteItem,
	form=QuoteItemForm,
	extra=0,
	can_delete=True,
	min_num=1,
	validate_min=True,
)


class OrderForm(forms.ModelForm):
	class Meta:
		model = Order
		fields = ['client', 'quote', 'issue_date', 'status', 'payment_terms', 'notes']
		widgets = {
			'issue_date': forms.DateInput(attrs={'type': 'date'}),
			'payment_terms': forms.TextInput(attrs={'placeholder': 'Ex.: 30/60 dias'}),
			'notes': forms.Textarea(attrs={'rows': 3}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		for field_name, lookup_type in (('client', 'clients'), ('quote', 'quotes')):
			field = self.fields.get(field_name)
			if field:
				field.widget.attrs.setdefault('class', 'select')
				field.widget.attrs['data-lookup-type'] = lookup_type
				field.widget.attrs.setdefault('data-lookup-placeholder', 'Buscar (F2)')


class OrderItemForm(forms.ModelForm):
	class Meta:
		model = OrderItem
		fields = ['product', 'description', 'quantity', 'unit_price', 'discount', 'sort_order']
		widgets = {
			'description': forms.TextInput(attrs={'placeholder': 'Descrição do item'}),
			'sort_order': forms.NumberInput(attrs={'min': 0}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		product_field = self.fields.get('product')
		if product_field:
			product_field.widget.attrs.setdefault('class', 'select')
			product_field.widget.attrs['data-lookup-type'] = 'products'
			product_field.widget.attrs.setdefault('data-lookup-placeholder', 'Buscar produtos (F2)')


OrderItemFormSet = inlineformset_factory(
	Order,
	OrderItem,
	form=OrderItemForm,
	extra=3,
	can_delete=True,
	min_num=1,
	validate_min=True,
)


class SalespersonForm(forms.ModelForm):
	user = forms.ModelChoiceField(
		queryset=get_user_model().objects.none(),
		label='Usuário',
		help_text='Selecione um usuário ativo para representar o vendedor.'
	)
	cpf = forms.CharField(max_length=14, label='CPF', widget=forms.TextInput(attrs={'placeholder': 'Somente números'}))

	class Meta:
		model = Salesperson
		fields = ['user', 'cpf', 'code', 'phone', 'is_active']
		labels = {
			'cpf': 'CPF',
			'code': 'Código',
			'phone': 'Telefone',
			'is_active': 'Ativo',
		}
		widgets = {
			'cpf': forms.TextInput(attrs={'placeholder': 'Somente números'}),
			'code': forms.TextInput(attrs={'readonly': 'readonly'}),
			'phone': forms.TextInput(attrs={'placeholder': 'Telefone comercial'}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		User = get_user_model()
		qs = User.objects.filter(is_active=True).order_by('first_name', 'last_name', 'username')
		if self.instance and self.instance.pk:
			self.fields['user'].queryset = qs.filter(pk=self.instance.user_id)
			self.fields['user'].disabled = True
		else:
			self.fields['user'].queryset = qs.exclude(salesperson_profile__isnull=False)
		self.fields['user'].widget.attrs.setdefault('class', 'select')
		self.fields['code'].disabled = True
		self.fields['code'].required = False
		self.fields['cpf'].widget.attrs.setdefault('class', 'input')
		self.fields['code'].widget.attrs.setdefault('class', 'input')
		self.fields['phone'].widget.attrs.setdefault('class', 'input')
		if self.instance and self.instance.pk:
			self.fields['cpf'].initial = self.instance.formatted_cpf
			self.fields['code'].initial = self.instance.code

	def clean_user(self):
		user = self.cleaned_data['user']
		if self.instance and self.instance.pk:
			return self.instance.user
		if Salesperson.objects.filter(user=user).exists():
			raise forms.ValidationError('Este usuário já está cadastrado como vendedor.')
		return user

	def clean_cpf(self):
		value = (self.cleaned_data.get('cpf') or '').strip()
		if not value:
			raise forms.ValidationError('Informe o CPF do vendedor.')
		try:
			digits = normalize_cpf(value)
		except ValueError as exc:
			raise forms.ValidationError(str(exc))
		self.cleaned_data['_cpf_digits'] = digits
		return digits

	def clean(self):
		data = super().clean()
		digits = self.cleaned_data.get('_cpf_digits')
		if digits:
			self.instance.cpf = digits
			self.instance.code = digits
			self.fields['code'].initial = digits
		return data
