from django.contrib import admin
from .models import ProdutoSync


@admin.register(ProdutoSync)
class ProdutoSyncAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descricao", "plu", "loja", "preco_normal", "estoque_disponivel")
    search_fields = ("codigo", "plu", "descricao", "referencia", "grupo", "subgrupo")
    list_filter = ("loja",)
    ordering = ("codigo",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
