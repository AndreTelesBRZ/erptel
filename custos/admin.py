from django.contrib import admin

from .models import CostBatch, CostBatchItem, CostParameter


@admin.register(CostParameter)
class CostParameterAdmin(admin.ModelAdmin):
	list_display = ('label', 'key', 'value', 'unit', 'is_percentage', 'is_active', 'updated_at')
	list_filter = ('is_percentage', 'is_active')
	search_fields = ('label', 'key', 'description')
	readonly_fields = ('created_at', 'updated_at')
	ordering = ('label',)


class CostBatchItemInline(admin.TabularInline):
	model = CostBatchItem
	extra = 0
	fields = ('code', 'unit_price', 'ipi_percent', 'freight_percent', 'st_value', 'replacement_cost')
	readonly_fields = ('st_value', 'replacement_cost')


@admin.register(CostBatch)
class CostBatchAdmin(admin.ModelAdmin):
	list_display = ('name', 'created_at', 'created_by', 'mva_percent', 'st_percent')
	search_fields = ('name', 'description')
	inlines = [CostBatchItemInline]
