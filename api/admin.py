# api/admin.py
from django.contrib import admin
from .models import ProdutoSync

@admin.register(ProdutoSync)
class ProdutoSyncAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descricao", "ean", "preco_normal", "estoque_disponivel", "loja")
    search_fields = ("codigo", "descricao", "ean", "referencia", "plu")
    ordering = ("codigo",)
    def has_add_permission(self, *args, **kwargs): return False
    def has_change_permission(self, *args, **kwargs): return False
    def has_delete_permission(self, *args, **kwargs): return False
