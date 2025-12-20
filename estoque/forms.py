from django import forms

from products.models import ProductSubGroup

from .models import CollectorInventoryItem, Inventory, InventoryItem


class InventoryForm(forms.ModelForm):
    class Meta:
        model = Inventory
        fields = [
            "name",
            "notes",
            "filter_query",
            "filter_in_stock_only",
            "filter_below_min_stock",
            "filter_group",
            "filter_subgroup",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input"}),
            "notes": forms.Textarea(attrs={"class": "textarea", "rows": 3}),
            "filter_query": forms.TextInput(attrs={"class": "input", "placeholder": "Nome, código, referência..."}),
            "filter_in_stock_only": forms.CheckboxInput(attrs={"class": "checkbox"}),
            "filter_below_min_stock": forms.CheckboxInput(attrs={"class": "checkbox"}),
            "filter_group": forms.Select(attrs={"class": "select"}),
            "filter_subgroup": forms.Select(attrs={"class": "select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        subgroup_field = self.fields["filter_subgroup"]
        queryset = ProductSubGroup.objects.select_related("group").order_by("group__name", "name")

        group_value = None
        if self.data:
            group_value = self.data.get(f"{self.prefix}-filter_group" if self.prefix else "filter_group")
        elif self.instance and self.instance.filter_group_id:
            group_value = self.instance.filter_group_id

        if group_value:
            try:
                subgroup_field.queryset = queryset.filter(group_id=group_value)
            except Exception:
                subgroup_field.queryset = queryset.none()
        else:
            subgroup_field.queryset = queryset


class InventoryCountForm(forms.ModelForm):
    counted_quantity = forms.DecimalField(
        label="Quantidade contada",
        required=False,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01"}),
    )
    recount_quantity = forms.DecimalField(
        label="Quantidade recontada",
        required=False,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01"}),
    )

    class Meta:
        model = InventoryItem
        fields = ["id", "counted_quantity", "recount_quantity"]


class InventorySelectionForm(forms.Form):
    name = forms.CharField(
        label="Nome do inventário",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "input"}),
    )
    notes = forms.CharField(
        label="Observações",
        required=False,
        widget=forms.Textarea(attrs={"class": "textarea", "rows": 3}),
    )


class InventoryImportForm(forms.Form):
    csv_file = forms.FileField(
        label="Arquivo CSV",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv", "class": "file-input"}),
    )
    close_inventory = forms.BooleanField(
        label="Fechar inventário automaticamente após importar",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "checkbox"}),
    )


class CollectorInventoryImportForm(forms.Form):
    arquivo = forms.FileField(
        label="Arquivo do coletor (.txt)",
        widget=forms.ClearableFileInput(attrs={"accept": ".txt", "class": "file-input"}),
    )


class CollectorInventoryItemForm(forms.ModelForm):
    count_1 = forms.DecimalField(
        label="1ª contagem",
        required=False,
        max_digits=15,
        decimal_places=3,
        widget=forms.NumberInput(attrs={"class": "input is-small", "step": "0.001"}),
    )
    count_2 = forms.DecimalField(
        label="2ª contagem",
        required=False,
        max_digits=15,
        decimal_places=3,
        widget=forms.NumberInput(attrs={"class": "input is-small", "step": "0.001"}),
    )
    new_count = forms.DecimalField(
        label="Nova contagem (+)",
        required=False,
        max_digits=15,
        decimal_places=3,
        widget=forms.NumberInput(attrs={"class": "input is-small", "step": "0.001", "placeholder": "0,000"}),
    )

    class Meta:
        model = CollectorInventoryItem
        fields = ["id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        counts = list(self.instance.contagens or [])
        self.fields["count_1"].initial = counts[0] if len(counts) > 0 else None
        self.fields["count_2"].initial = counts[1] if len(counts) > 1 else None
        self.extra_counts = counts[2:] if len(counts) > 2 else []

    def save(self, commit=True):
        instance = super().save(commit=False)
        counts = []

        count_1 = self.cleaned_data.get("count_1")
        count_2 = self.cleaned_data.get("count_2")
        if count_1 is not None:
            counts.append(count_1)
        if count_2 is not None:
            counts.append(count_2)

        existing_extra = list(self.instance.contagens[2:]) if len(self.instance.contagens) > 2 else []
        counts.extend(existing_extra)

        new_count = self.cleaned_data.get("new_count")
        if new_count is not None:
            counts.append(new_count)

        if counts != list(self.instance.contagens):
            instance.set_counts(counts)
        return instance
