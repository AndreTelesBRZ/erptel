from decimal import Decimal

from django import forms
from companies.models import Company

from django.forms import inlineformset_factory, BaseInlineFormSet

from core.utils.documents import (
	normalize_cnpj,
	normalize_cpf,
)
from .models import (
	Product,
	Supplier,
	ProductGroup,
	ProductSubGroup,
	SupplierProductPrice,
	PriceAdjustmentBatch,
	ProductStock,
	Brand,
	Category,
	Department,
	Volume,
	UnitOfMeasure,
)


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        # include all editable fields; exclude auto fields
        exclude = ('id', 'created_at')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'short_description': forms.Textarea(attrs={'rows': 2}),
            'additional_info': forms.Textarea(attrs={'rows': 3}),
            'price': forms.NumberInput(attrs={'step': '0.01'}),
            'stock': forms.NumberInput(attrs={'step': '0.01', 'inputmode': 'decimal'}),
            'cost_price': forms.NumberInput(attrs={'step': '0.0001'}),
            'pricing_base_cost': forms.NumberInput(attrs={'step': '0.01'}),
            'pricing_variable_expense_percent': forms.NumberInput(attrs={'step': '0.01'}),
            'pricing_fixed_expense_percent': forms.NumberInput(attrs={'step': '0.01'}),
            'pricing_tax_percent': forms.NumberInput(attrs={'step': '0.01'}),
            'pricing_desired_margin_percent': forms.NumberInput(attrs={'step': '0.01'}),
            'pricing_markup_factor': forms.NumberInput(attrs={'step': '0.0001'}),
            'pricing_suggested_price': forms.NumberInput(attrs={'step': '0.01'}),
            'weight_net': forms.NumberInput(attrs={'step': '0.001'}),
            'weight_gross': forms.NumberInput(attrs={'step': '0.001'}),
            'expiration_date': forms.DateInput(attrs={'type': 'date'}),
            'lifecycle_start_date': forms.DateInput(attrs={'type': 'date'}),
            'lifecycle_end_date': forms.DateInput(attrs={'type': 'date'}),
            'brand_obj': forms.Select(attrs={'class': 'select'}),
            'supplier_obj': forms.Select(attrs={'class': 'select'}),
            'category_obj': forms.Select(attrs={'class': 'select'}),
            'department_obj': forms.Select(attrs={'class': 'select'}),
            'volumes_obj': forms.Select(attrs={'class': 'select'}),
            'unit_of_measure_obj': forms.Select(attrs={'class': 'select'}),
        }

    companies = forms.ModelMultipleChoiceField(
        queryset=Company.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='Empresas'
    )

    # We'll render the multiple attribute in the template to avoid widget init validation
    images = forms.FileField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        company_field = self.fields['companies']
        company_field.queryset = Company.objects.filter(is_active=True).order_by('trade_name', 'name')
        company_field.widget.attrs.setdefault('class', 'checkbox-list')
        if 'stock' in self.fields:
            self.fields['stock'].localize = True
            self.fields['stock'].widget.attrs.setdefault('placeholder', 'Calculado automaticamente')
            self.fields['stock'].widget.attrs['readonly'] = 'readonly'
            self.fields['stock'].help_text = 'Total calculado a partir dos estoques por empresa.'
        lookup_fields = {
            'supplier_obj': ('suppliers', Supplier.objects.order_by('name')),
            'brand_obj': ('brands', Brand.objects.order_by('name')),
            'category_obj': ('categories', Category.objects.order_by('name')),
            'department_obj': ('departments', Department.objects.order_by('name')),
            'volumes_obj': ('volumes', Volume.objects.order_by('description')),
            'unit_of_measure_obj': ('units', UnitOfMeasure.objects.order_by('code')),
            'product_group': ('product_groups', ProductGroup.objects.order_by('name')),
            'product_subgroup': ('product_subgroups', ProductSubGroup.objects.order_by('name')),
        }
        placeholder_map = {
            'suppliers': 'Buscar fornecedores (F2)',
            'brands': 'Buscar marcas (F2)',
            'categories': 'Buscar categorias (F2)',
            'departments': 'Buscar departamentos (F2)',
            'volumes': 'Buscar volumes (F2)',
            'units': 'Buscar unidades (F2)',
            'product_groups': 'Buscar grupos de produtos (F2)',
            'product_subgroups': 'Buscar subgrupos (F2)',
        }
        for field_name, (lookup_type, queryset) in lookup_fields.items():
            field = self.fields.get(field_name)
            if not field:
                continue
            field.queryset = queryset
            field.widget.attrs.setdefault('class', 'select')
            field.widget.attrs['data-lookup-type'] = lookup_type
            placeholder = field.widget.attrs.get('data-lookup-placeholder')
            if not placeholder:
                field.widget.attrs['data-lookup-placeholder'] = placeholder_map.get(lookup_type, 'Buscar (F2)')
            field.empty_label = '—'
        label_overrides = {
            'supplier_obj': 'Fornecedor (cadastro)',
            'brand_obj': 'Marca (cadastro)',
            'category_obj': 'Categoria (cadastro)',
            'department_obj': 'Departamento (cadastro)',
            'volumes_obj': 'Volume (cadastro)',
            'unit_of_measure_obj': 'Unidade de medida (cadastro)',
            'product_group': 'Grupo de produtos',
            'product_subgroup': 'Subgrupo de produtos',
        }
        for field_name, label in label_overrides.items():
            if field_name in self.fields:
                self.fields[field_name].label = label
        pricing_labels = {
            'pricing_base_cost': 'Custo base para precificação',
            'pricing_variable_expense_percent': 'Despesas variáveis (%)',
            'pricing_fixed_expense_percent': 'Despesas fixas rateadas (%)',
            'pricing_tax_percent': 'Tributos sobre venda (%)',
            'pricing_desired_margin_percent': 'Margem de lucro desejada (%)',
            'pricing_markup_factor': 'Markup calculado',
            'pricing_suggested_price': 'Preço sugerido pela fórmula',
        }
        for field, label in pricing_labels.items():
            if field in self.fields:
                self.fields[field].label = label
                self.fields[field].required = False


class PriceAdjustmentForm(forms.Form):
	rule_type = forms.ChoiceField(
		label='Regra de reajuste',
		choices=PriceAdjustmentBatch.Rule.choices,
	)
	percent = forms.DecimalField(
		label='Percentual (%)',
		required=False,
		max_digits=6,
		decimal_places=2,
		widget=forms.NumberInput(attrs={'step': '0.01', 'placeholder': 'Ex.: 5 para +5%'}),
		help_text='Variação aplicada sobre o preço atual.',
	)
	target_margin = forms.DecimalField(
		label='Margem desejada (%)',
		required=False,
		max_digits=6,
		decimal_places=2,
		widget=forms.NumberInput(attrs={'step': '0.01', 'placeholder': 'Ex.: 35 para 35%'}),
		help_text='Considera o custo cadastrado para sugerir o novo preço.',
	)
	notes = forms.CharField(
		label='Observações',
		required=False,
		widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Opcional: indique motivo ou contexto do reajuste.'}),
	)

	def clean(self):
		cleaned = super().clean()
		rule = cleaned.get('rule_type')
		if not rule:
			return cleaned
		if rule == PriceAdjustmentBatch.Rule.INCREASE_PERCENT:
			percent = cleaned.get('percent')
			if percent is None:
				self.add_error('percent', 'Informe o percentual de ajuste.')
		elif rule == PriceAdjustmentBatch.Rule.SET_MARGIN:
			margin = cleaned.get('target_margin')
			if margin is None:
				self.add_error('target_margin', 'Informe a margem desejada.')
			elif margin >= Decimal('100'):
				self.add_error('target_margin', 'A margem deve ser inferior a 100%.')
		return cleaned

	def get_parameters(self):
		rule = self.cleaned_data.get('rule_type')
		params = {}
		if rule == PriceAdjustmentBatch.Rule.INCREASE_PERCENT:
			params['percent'] = str(self.cleaned_data.get('percent'))
		elif rule == PriceAdjustmentBatch.Rule.SET_MARGIN:
			params['target_margin'] = str(self.cleaned_data.get('target_margin'))
		return params


class SupplierCatalogBulkForm(forms.Form):
	supplier = forms.ModelChoiceField(
		queryset=Supplier.objects.order_by('name'),
		label='Fornecedor',
		widget=forms.Select(attrs={'class': 'select'}),
	)
	valid_from = forms.DateField(
		label='Início de vigência',
		widget=forms.DateInput(attrs={'type': 'date', 'class': 'input'}),
	)
	valid_until = forms.DateField(
		label='Fim de vigência',
		required=False,
		widget=forms.DateInput(attrs={'type': 'date', 'class': 'input'}),
	)

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['supplier'].widget.attrs['data-lookup-type'] = 'suppliers'
		self.fields['supplier'].widget.attrs.setdefault('data-lookup-placeholder', 'Buscar fornecedores (F2)')


class ProductStockForm(forms.ModelForm):
    class Meta:
        model = ProductStock
        fields = ['company', 'quantity', 'min_quantity', 'max_quantity']
        widgets = {
            'company': forms.Select(attrs={'class': 'select'}),
            'quantity': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'min_quantity': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'max_quantity': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        company_queryset = kwargs.pop('company_queryset', None)
        super().__init__(*args, **kwargs)
        qs = company_queryset or Company.objects.filter(is_active=True).order_by('trade_name', 'name')
        self.fields['company'].queryset = qs


class BaseProductStockFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        seen = set()
        for form in self.forms:
            if not hasattr(form, 'cleaned_data'):
                continue
            if not form.has_changed():
                continue
            if form.cleaned_data.get('DELETE'):
                continue
            company = form.cleaned_data.get('company')
            quantity = form.cleaned_data.get('quantity')
            min_qty = form.cleaned_data.get('min_quantity')
            max_qty = form.cleaned_data.get('max_quantity')
            if not company and quantity in (None, '', Decimal('0')) and min_qty in (None, '', Decimal('0')) and max_qty in (None, '', Decimal('0')):
                continue
            if not company:
                raise forms.ValidationError('Informe a empresa para cada estoque.')
            if company.pk in seen:
                raise forms.ValidationError('Cada empresa deve aparecer apenas uma vez na lista de estoques.')
            seen.add(company.pk)


ProductStockFormSet = inlineformset_factory(
    Product,
    ProductStock,
    form=ProductStockForm,
    formset=BaseProductStockFormSet,
    extra=2,
    can_delete=True,
)


class ProductGroupForm(forms.ModelForm):
	class Meta:
		model = ProductGroup
		fields = ['parent_group', 'name']
		widgets = {
			'name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Nome do grupo'}),
			'parent_group': forms.Select(attrs={'class': 'select'}),
		}
		labels = {'name': 'Nome do grupo', 'parent_group': 'Grupo pai'}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['parent_group'].required = False
		if self.instance and self.instance.pk:
			self.fields['parent_group'].queryset = ProductGroup.objects.exclude(pk=self.instance.pk)
		else:
			self.fields['parent_group'].queryset = ProductGroup.objects.all()


class ProductSubGroupForm(forms.ModelForm):
	class Meta:
		model = ProductSubGroup
		fields = ['group', 'parent_subgroup', 'name']
		widgets = {
			'group': forms.Select(attrs={'class': 'select'}),
			'parent_subgroup': forms.Select(attrs={'class': 'select'}),
			'name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Nome do subgrupo'}),
		}
		labels = {
			'group': 'Grupo principal',
			'parent_subgroup': 'Subgrupo pai (opcional)',
			'name': 'Nome do subgrupo',
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['parent_subgroup'].required = False
		if self.instance and self.instance.pk:
			self.fields['parent_subgroup'].queryset = ProductSubGroup.objects.exclude(pk=self.instance.pk).order_by('group__name', 'name')
		else:
			self.fields['parent_subgroup'].queryset = ProductSubGroup.objects.order_by('group__name', 'name')
		self.fields['group'].queryset = ProductGroup.objects.order_by('name')

	def clean(self):
		cleaned = super().clean()
		parent = cleaned.get('parent_subgroup')
		group = cleaned.get('group')
		if parent and group and parent.group_id != group.id:
			self.add_error('parent_subgroup', 'Selecione um subgrupo pai pertencente ao mesmo grupo.')
		if parent and self.instance.pk:
			ancestor = parent
			while ancestor:
				if ancestor.pk == self.instance.pk:
					self.add_error('parent_subgroup', 'Não é possível criar um ciclo de subgrupos.')
					break
				ancestor = ancestor.parent_subgroup
		return cleaned


class SupplierProductPriceForm(forms.ModelForm):
	class Meta:
		model = SupplierProductPrice
		fields = [
			'product',
			'code',
			'description',
			'unit',
			'quantity',
			'pack_quantity',
			'unit_price',
			'ipi_percent',
			'freight_percent',
			'st_percent',
			'replacement_cost',
			'valid_from',
			'valid_until',
		]
		widgets = {
			'product': forms.Select(attrs={'class': 'select'}),
			'valid_from': forms.DateInput(attrs={'type': 'date'}),
			'valid_until': forms.DateInput(attrs={'type': 'date'}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['product'].required = False
		self.fields['product'].queryset = Product.objects.order_by('name')

	def clean(self):
		cleaned = super().clean()
		product = cleaned.get('product')
		code = (cleaned.get('code') or '').strip()
		if product:
			if not code:
				code = product.code or product.reference or str(product.pk)
				cleaned['code'] = code
				self.cleaned_data['code'] = code
			if not cleaned.get('description'):
				desc = product.name
				cleaned['description'] = desc
				self.cleaned_data['description'] = desc
			if not cleaned.get('unit') and product.unit:
				cleaned['unit'] = product.unit
				self.cleaned_data['unit'] = product.unit
		if not code:
			self.add_error('code', 'Informe o código do item.')
		return cleaned


class SupplierProductPriceImportForm(forms.Form):
	file = forms.FileField(label='Arquivo CSV')


class ProductImportForm(forms.Form):
    csv_file = forms.FileField(label='Arquivo CSV')
    dry_run = forms.BooleanField(label='Simular (validar sem gravar)', required=False)


class SupplierForm(forms.ModelForm):
	document = forms.CharField(max_length=20, label='CPF/CNPJ', widget=forms.TextInput(attrs={'placeholder': 'Somente números'}))

	class Meta:
		model = Supplier
		fields = [
			'name',
			'person_type',
			'document',
			'code',
			'state_registration',
			'email',
			'phone',
			'address',
			'number',
			'complement',
			'district',
			'city',
			'state',
			'zip_code',
			'notes',
		]
		labels = {
			'name': 'Nome',
			'person_type': 'Tipo de pessoa',
			'document': 'CPF/CNPJ',
			'code': 'Código',
			'state_registration': 'Inscrição estadual',
			'email': 'E-mail',
			'phone': 'Telefone',
			'address': 'Endereço',
			'number': 'Número',
			'complement': 'Complemento',
			'district': 'Bairro',
			'city': 'Cidade',
			'state': 'UF',
			'zip_code': 'CEP',
			'notes': 'Observações',
		}
		widgets = {
			'name': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Razão social / Nome'}),
			'person_type': forms.Select(attrs={'class': 'select'}),
			'document': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Informe o CPF ou CNPJ'}),
			'code': forms.TextInput(attrs={'class': 'input', 'readonly': 'readonly'}),
			'state_registration': forms.TextInput(attrs={'class': 'input'}),
			'email': forms.EmailInput(attrs={'class': 'input'}),
			'phone': forms.TextInput(attrs={'class': 'input', 'placeholder': '(00) 0000-0000'}),
			'address': forms.TextInput(attrs={'class': 'input'}),
			'number': forms.TextInput(attrs={'class': 'input'}),
			'complement': forms.TextInput(attrs={'class': 'input'}),
			'district': forms.TextInput(attrs={'class': 'input'}),
			'city': forms.TextInput(attrs={'class': 'input'}),
			'state': forms.TextInput(attrs={'class': 'input', 'maxlength': '2'}),
			'zip_code': forms.TextInput(attrs={'class': 'input', 'placeholder': '00000-000'}),
			'notes': forms.Textarea(attrs={'class': 'textarea', 'rows': 3}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['code'].disabled = True
		self.fields['code'].required = False

		for field_name in ['state_registration', 'email', 'phone', 'address', 'number', 'complement', 'district', 'city', 'state', 'zip_code', 'notes']:
			if field_name in self.fields:
				self.fields[field_name].required = False
		if self.instance and self.instance.pk:
			self.fields['document'].initial = self.instance.formatted_document

	def clean_document(self):
		value = (self.cleaned_data.get('document') or '').strip()
		person_type = self.cleaned_data.get('person_type') or Supplier.PersonType.LEGAL
		if not value:
			raise forms.ValidationError('Informe o CPF ou CNPJ.')
		try:
			if person_type == Supplier.PersonType.LEGAL:
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
			self.fields['code'].initial = digits
		return data
