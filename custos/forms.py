from django import forms

from .models import CostBatch, CostBatchItem, CostParameter
from products.models import SupplierProductPrice


class CostParameterForm(forms.ModelForm):
	class Meta:
		model = CostParameter
		fields = [
			'label',
			'key',
			'value',
			'unit',
			'is_percentage',
			'description',
			'is_active',
		]
		widgets = {
			'label': forms.TextInput(attrs={'class': 'input'}),
			'key': forms.TextInput(attrs={'class': 'input', 'pattern': r'[a-z0-9\-]+'}),
			'value': forms.NumberInput(attrs={'class': 'input', 'step': '0.0001'}),
			'unit': forms.TextInput(attrs={'class': 'input'}),
			'description': forms.Textarea(attrs={'class': 'textarea', 'rows': 3}),
		}


class SupplierCostForm(forms.ModelForm):
	class Meta:
		model = SupplierProductPrice
		fields = ['unit_price', 'ipi_percent', 'freight_percent']
		widgets = {
			'unit_price': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': '0'}),
			'ipi_percent': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': '0'}),
			'freight_percent': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': '0'}),
		}


class CostBatchForm(forms.ModelForm):
	class Meta:
		model = CostBatch
		fields = [
			'name',
			'description',
			'default_ipi_percent',
			'default_freight_percent',
			'mva_percent',
			'st_multiplier',
			'st_percent',
		]
		widgets = {
			'name': forms.TextInput(attrs={'class': 'input'}),
			'description': forms.Textarea(attrs={'class': 'textarea', 'rows': 3}),
			'default_ipi_percent': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': '0'}),
			'default_freight_percent': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': '0'}),
			'mva_percent': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': '0'}),
			'st_multiplier': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': '0'}),
			'st_percent': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': '0'}),
		}


class CostBatchItemForm(forms.ModelForm):
	class Meta:
		model = CostBatchItem
		fields = ['unit_price', 'ipi_percent', 'freight_percent']
		widgets = {
			'unit_price': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': '0'}),
			'ipi_percent': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': '0'}),
			'freight_percent': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': '0'}),
		}


class CostBatchAddItemsForm(forms.Form):
	codes = forms.CharField(
		label='Códigos dos itens',
		widget=forms.Textarea(attrs={'class': 'textarea', 'rows': 3, 'placeholder': 'Informe códigos separados por vírgula ou nova linha'}),
	)

	def clean_codes(self):
		raw = self.cleaned_data['codes']
		parts = [part.strip() for part in raw.replace(';', ',').replace('\n', ',').split(',') if part.strip()]
		if not parts:
			raise forms.ValidationError('Informe ao menos um código de item.')
		return parts
