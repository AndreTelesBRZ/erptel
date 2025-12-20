from django.contrib import admin

from .models import PurchaseOrder


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'supplier', 'status', 'total_amount', 'expected_date', 'created_at')
    list_filter = ('status', 'expected_date', 'created_at')
    search_fields = ('order_number', 'supplier', 'notes')
    ordering = ('-created_at',)

# Register your models here.
