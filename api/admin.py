# api/admin.py
import csv
from decimal import Decimal
from io import StringIO

from django.contrib import admin, messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import path
from django.utils import timezone

from .models import ProdutoSync, PlanoPagamentoCliente

@admin.register(ProdutoSync)
class ProdutoSyncAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descricao", "ean", "preco_normal", "estoque_disponivel", "loja")
    search_fields = ("codigo", "descricao", "ean", "referencia", "plu")
    ordering = ("codigo",)
    def has_add_permission(self, *args, **kwargs): return False
    def has_change_permission(self, *args, **kwargs): return False
    def has_delete_permission(self, *args, **kwargs): return False


@admin.register(PlanoPagamentoCliente)
class PlanoPagamentoClienteAdmin(admin.ModelAdmin):
    list_display = (
        "cliente_codigo",
        "loja_codigo",
        "plano_codigo",
        "plano_descricao",
        "parcelas",
        "dias_primeira_parcela",
        "dias_entre_parcelas",
        "valor_minimo",
        "valor_acrescimo",
        "updated_at",
    )
    list_filter = ("loja_codigo",)
    search_fields = ("cliente_codigo", "plano_codigo", "plano_descricao")
    ordering = ("loja_codigo", "cliente_codigo", "plano_codigo")
    change_list_template = "admin/api/planopagamentocliente/change_list.html"
    actions = ["export_csv"]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "import-csv/",
                self.admin_site.admin_view(self.import_csv),
                name="api_planopagamentocliente_import_csv",
            ),
            path(
                "export-csv/",
                self.admin_site.admin_view(self.export_csv_view),
                name="api_planopagamentocliente_export_csv",
            ),
        ]
        return custom_urls + urls

    def export_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="planos_pagamento.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "cliente_codigo",
                "loja_codigo",
                "plano_codigo",
                "plano_descricao",
                "parcelas",
                "dias_primeira_parcela",
                "dias_entre_parcelas",
                "valor_minimo",
                "valor_acrescimo",
            ]
        )
        for plan in queryset.iterator():
            writer.writerow(
                [
                    plan.cliente_codigo,
                    plan.loja_codigo,
                    plan.plano_codigo,
                    plan.plano_descricao,
                    plan.parcelas,
                    plan.dias_primeira_parcela,
                    plan.dias_entre_parcelas,
                    plan.valor_minimo,
                    plan.valor_acrescimo,
                ]
            )
        return response

    export_csv.short_description = "Exportar CSV (selecionados)"

    def export_csv_view(self, request):
        qs = self.get_queryset(request)
        return self.export_csv(request, qs)

    def import_csv(self, request):
        if request.method != "POST":
            return render(request, "admin/api/planopagamentocliente/import_csv.html")

        upload = request.FILES.get("csv_file")
        if not upload:
            messages.error(request, "Nenhum arquivo enviado.")
            return redirect("..")

        try:
            decoded = upload.read().decode("utf-8")
        except UnicodeDecodeError:
            decoded = upload.read().decode("latin-1")

        reader = csv.DictReader(StringIO(decoded))
        required = {"cliente_codigo", "loja_codigo", "plano_codigo"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            messages.error(request, "CSV invalido. Campos obrigatorios: cliente_codigo, loja_codigo, plano_codigo.")
            return redirect("..")

        now = timezone.now()
        rows = []
        for idx, row in enumerate(reader, start=2):
            try:
                rows.append(
                    PlanoPagamentoCliente(
                        cliente_codigo=(row.get("cliente_codigo") or "").strip(),
                        loja_codigo=(row.get("loja_codigo") or "").strip(),
                        plano_codigo=(row.get("plano_codigo") or "").strip(),
                        plano_descricao=(row.get("plano_descricao") or "").strip(),
                        parcelas=_parse_int(row.get("parcelas")),
                        dias_primeira_parcela=_parse_int(row.get("dias_primeira_parcela")),
                        dias_entre_parcelas=_parse_int(row.get("dias_entre_parcelas")),
                        valor_minimo=_parse_decimal(row.get("valor_minimo")),
                        valor_acrescimo=_parse_decimal(row.get("valor_acrescimo")),
                        updated_at=now,
                    )
                )
            except Exception as exc:
                messages.error(request, f"Linha {idx} invalida: {exc}")
                return redirect("..")

        if not rows:
            messages.warning(request, "CSV sem linhas validas.")
            return redirect("..")

        with transaction.atomic():
            PlanoPagamentoCliente.objects.bulk_create(
                rows,
                update_conflicts=True,
                unique_fields=["cliente_codigo", "loja_codigo", "plano_codigo"],
                update_fields=[
                    "plano_descricao",
                    "parcelas",
                    "dias_primeira_parcela",
                    "dias_entre_parcelas",
                    "valor_minimo",
                    "valor_acrescimo",
                    "updated_at",
                ],
            )

        messages.success(request, f"Importacao concluida: {len(rows)} registros.")
        return redirect("..")


def _parse_int(value):
    if value in (None, ""):
        return None
    return int(str(value).strip())


def _parse_decimal(value):
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if "," in raw and "." not in raw:
        raw = raw.replace(",", ".")
    return Decimal(raw)
