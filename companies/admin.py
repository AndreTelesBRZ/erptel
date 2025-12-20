from django.contrib import admin

from .models import Company


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
	list_display = ('name', 'trade_name', 'tax_id', 'tax_regime', 'is_active')
	list_filter = ('is_active', 'tax_regime')
	search_fields = ('name', 'trade_name', 'tax_id', 'email')

# Register your models here.
