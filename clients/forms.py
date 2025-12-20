from django import forms

from core.utils.documents import (
	format_cnpj,
	format_cpf,
	normalize_cnpj,
	normalize_cpf,
)
from .models import Client


class ClientForm(forms.ModelForm):
	document = forms.CharField(max_length=20, label='CPF/CNPJ', widget=forms.TextInput(attrs={'placeholder': 'Somente números'}))

	class Meta:
		model = Client
		fields = [
			'person_type',
			'document',
			'code',
			'first_name',
			'last_name',
			'email',
			'phone',
			'state_registration',
			'address',
			'number',
			'complement',
			'district',
			'city',
			'state',
			'zip_code',
		]
		labels = {
			'document': 'CPF/CNPJ',
			'code': 'Código',
			'first_name': 'Nome / Razão social',
			'last_name': 'Sobrenome / Nome fantasia',
			'phone': 'Telefone',
			'state_registration': 'Inscrição Estadual',
			'address': 'Endereço',
			'number': 'Número',
			'complement': 'Complemento',
			'district': 'Bairro',
			'city': 'Cidade',
			'state': 'UF',
			'zip_code': 'CEP',
		}
		widgets = {
			'person_type': forms.Select(attrs={'class': 'select'}),
			'phone': forms.TextInput(attrs={'placeholder': '(00) 00000-0000'}),
			'state_registration': forms.TextInput(attrs={'class': 'input'}),
			'address': forms.TextInput(attrs={'class': 'input'}),
			'number': forms.TextInput(attrs={'class': 'input'}),
			'complement': forms.TextInput(attrs={'class': 'input'}),
			'district': forms.TextInput(attrs={'class': 'input'}),
			'city': forms.TextInput(attrs={'class': 'input'}),
			'state': forms.TextInput(attrs={'class': 'input', 'maxlength': '2'}),
			'zip_code': forms.TextInput(attrs={'class': 'input', 'placeholder': '00000-000'}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if 'code' in self.fields:
			self.fields['code'].disabled = True
			self.fields['code'].required = False
			self.fields['code'].widget.attrs.setdefault('readonly', 'readonly')
			self.fields['code'].widget.attrs.setdefault('class', 'input')
		if 'document' in self.fields:
			self.fields['document'].widget.attrs.setdefault('class', 'input')
			self.fields['document'].widget.attrs.setdefault('placeholder', 'Somente números')
		if 'person_type' in self.fields:
			self.fields['person_type'].widget.attrs.setdefault('class', 'select')
		for field_name in ('first_name', 'last_name', 'email', 'phone'):
			if field_name in self.fields:
				self.fields[field_name].widget.attrs.setdefault('class', 'input')
		for field_name in ('state_registration', 'address', 'number', 'complement', 'district', 'city', 'state', 'zip_code'):
			if field_name in self.fields:
				self.fields[field_name].required = False
				self.fields[field_name].widget.attrs.setdefault('class', 'input')

		if self.instance and self.instance.pk:
			document_field = self.fields.get('document')
			if document_field:
				document_field.initial = self.instance.formatted_document

	def clean_document(self):
		value = (self.cleaned_data.get('document') or '').strip()
		person_type = self.cleaned_data.get('person_type') or Client.PersonType.INDIVIDUAL
		if not value:
			raise forms.ValidationError('Informe o CPF ou CNPJ.')
		try:
			if person_type == Client.PersonType.LEGAL:
				digits = normalize_cnpj(value)
			else:
				digits = normalize_cpf(value)
		except ValueError as exc:
			raise forms.ValidationError(str(exc))
		self.cleaned_data['_document_digits'] = digits
		return digits

	def clean(self):
		data = super().clean()
		digits = self.cleaned_data.get('_document_digits')
		if digits:
			self.instance.document = digits
			self.instance.code = digits
			if 'code' in self.fields:
				self.fields['code'].initial = digits
		return data
