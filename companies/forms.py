from django import forms

from core.utils.documents import normalize_cnpj, format_cnpj
from .models import Company


class CompanyForm(forms.ModelForm):
	class Meta:
		model = Company
		fields = [
			'code',
			'name',
			'trade_name',
			'tax_id',
			'state_registration',
			'email',
			'phone',
			'website',
			'address',
			'number',
			'complement',
			'district',
			'city',
			'state',
			'zip_code',
			'tax_regime',
			'tax_agent',
			'default_discount_percent',
			'max_discount_percent',
			'notes',
			'is_active',
		]
		widgets = {
			'notes': forms.Textarea(attrs={'rows': 3}),
			'default_discount_percent': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': '0'}),
			'max_discount_percent': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': '0'}),
			'tax_regime': forms.Select(attrs={'class': 'select'}),
			'tax_agent': forms.Select(attrs={'class': 'select'}),
			'is_active': forms.CheckboxInput(attrs={'class': 'checkbox'}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if 'code' in self.fields:
			self.fields['code'].disabled = True
			self.fields['code'].required = False
			self.fields['code'].widget.attrs.setdefault('readonly', 'readonly')
			self.fields['code'].widget.attrs.setdefault('class', 'input')

	def clean_tax_id(self):
		raw = (self.cleaned_data.get('tax_id') or '').strip()
		if not raw:
			return raw
		digits = normalize_cnpj(raw)
		self.cleaned_data['_tax_id_digits'] = digits
		return format_cnpj(digits)

	def clean(self):
		cleaned_data = super().clean()
		digits = self.cleaned_data.get('_tax_id_digits')
		if digits:
			self.instance.code = digits
			if 'code' in self.fields:
				self.cleaned_data['code'] = digits
				self.fields['code'].initial = digits
		return cleaned_data
