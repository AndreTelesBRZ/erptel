from django import forms
from .models import Product


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "description", "price"]


class ProductImportForm(forms.Form):
    csv_file = forms.FileField(label='Arquivo CSV')
