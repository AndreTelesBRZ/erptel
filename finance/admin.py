from django.contrib import admin

from .models import FinanceEntry


@admin.register(FinanceEntry)
class FinanceEntryAdmin(admin.ModelAdmin):
    list_display = ('title', 'entry_type', 'category', 'amount', 'due_date', 'paid', 'created_at')
    list_filter = ('entry_type', 'paid', 'due_date', 'category')
    search_fields = ('title', 'category', 'notes')
    ordering = ('-due_date', '-created_at')

# Register your models here.
