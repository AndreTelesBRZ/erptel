# api/admin.py
from django.contrib import admin

from .models import PlanoPagamentoCliente, ProdutoSync


@admin.register(ProdutoSync)
class ProdutoSyncAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descricao", "ean", "preco_normal", "estoque_disponivel", "loja")
    search_fields = ("codigo", "descricao", "ean", "referencia", "plu")
    ordering = ("codigo",)

    def has_add_permission(self, *args, **kwargs):  # pragma: no cover - read-only view
        return False

    def has_change_permission(self, *args, **kwargs):  # pragma: no cover
        return False

    def has_delete_permission(self, *args, **kwargs):  # pragma: no cover
        return False


@admin.register(PlanoPagamentoCliente)
class PlanoPagamentoClienteAdmin(admin.ModelAdmin):
    list_display = (
        "plano_codigo",
        "cliente_codigo",
        "display_descricao",
        "quantidade_parcelas",
        "valor_minimo",
        "updated_at",
    )
    list_filter = ("cliente_codigo",)
    search_fields = ("plano_codigo", "cliente_codigo", "plano_descricao")
    ordering = ("cliente_codigo", "plano_codigo")
    readonly_fields = ("updated_at",)
    fieldsets = (
        (
            "Identificação",
            {
                "fields": (
                    "cliente_codigo",
                    "plano_codigo",
                    "plano_descricao",
                )
            },
        ),
        (
            "Condições",
            {
                "fields": (
                    "entrada_percentual",
                    "intervalo_primeira_parcela",
                    "intervalo_parcelas",
                    "quantidade_parcelas",
                    "valor_acrescimo",
                    "valor_minimo",
                ),
                "description": "Configure os valores e intervalos aplicáveis a este plano.",
            },
        ),
        ("Metadados", {"fields": ("updated_at",)}),
    )

    def _is_admin(self, request):
        return bool(request.user and request.user.is_staff)

    def has_module_permission(self, request):
        return self._is_admin(request)

    def has_view_permission(self, request, obj=None):
        return self._is_admin(request)

    def has_add_permission(self, request):
        return self._is_admin(request)

    def has_change_permission(self, request, obj=None):
        return self._is_admin(request)

    def has_delete_permission(self, request, obj=None):
        return self._is_admin(request)

    @admin.display(description="Descrição")
    def display_descricao(self, obj):
        return obj.plano_descricao
