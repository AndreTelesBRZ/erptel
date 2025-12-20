import csv
import io
import re
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import Coalesce
from django.forms import modelformset_factory
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from products.models import Product
from products.utils import format_decimal, parse_decimal

from .forms import (
    CollectorInventoryImportForm,
    CollectorInventoryItemForm,
    InventoryCountForm,
    InventoryForm,
    InventoryImportForm,
    InventorySelectionForm,
)
from .models import (
    CollectorInventoryItem,
    Inventory,
    InventoryItem,
    InventorySelection,
    ZERO_DECIMAL,
)

InventoryCountFormSet = modelformset_factory(
    InventoryItem,
    form=InventoryCountForm,
    extra=0,
    can_delete=False,
)

CollectorInventoryFormSet = modelformset_factory(
    CollectorInventoryItem,
    form=CollectorInventoryItemForm,
    extra=0,
    can_delete=False,
)

INVENTORY_EXPORT_HEADERS = [
    "Inventário ID",
    "Inventário",
    "Loja",
    "Item ID",
    "Produto ID",
    "Código",
    "Descrição",
    "Referência",
    "Quantidade disponível",
    "Contagem",
    "Recontagem",
    "Encerramento",
]

INVENTORY_IMPORT_FIELD_MAP = {
    "Contagem": "counted_quantity",
    "Recontagem": "recount_quantity",
    "Encerramento": "final_quantity",
}

COLLECTOR_QUANTITY_FACTOR = Decimal("1000")
PLU_MAPPING_PATH = Path("/home/ubuntu/apps/Django/.venv/plu.csv")


def _normalize_plu_value(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits:
        stripped = digits.lstrip("0")
        return stripped or "0"
    return raw


@lru_cache(maxsize=1)
def _load_plu_mapping() -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not PLU_MAPPING_PATH.exists():
        return mapping
    try:
        with PLU_MAPPING_PATH.open("r", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            if not reader.fieldnames:
                return mapping
            fields = [field.strip().lower() for field in reader.fieldnames]
            try:
                idx_code = fields.index("codigo")
                idx_plu = fields.index("plu")
            except ValueError:
                return mapping
            code_field = reader.fieldnames[idx_code]
            plu_field = reader.fieldnames[idx_plu]
            for row in reader:
                raw_code = (row.get(code_field) or "").strip()
                raw_plu = _normalize_plu_value(row.get(plu_field))
                if not raw_code or not raw_plu:
                    continue
                candidates = {raw_code, raw_code.lstrip("0")}
                digits = "".join(ch for ch in raw_code if ch.isdigit())
                if digits:
                    candidates.add(digits)
                    candidates.add(digits.lstrip("0"))
                for candidate in candidates:
                    if candidate:
                        mapping[candidate] = raw_plu
    except Exception:
        return {}
    return mapping


def _get_mapped_plu(code: str) -> str | None:
    mapping = _load_plu_mapping()
    cleaned = _normalize_code(code)
    if not cleaned:
        return None
    digits = "".join(ch for ch in cleaned if ch.isdigit())
    candidates = {
        cleaned,
        cleaned.lstrip("0"),
        digits,
        digits.lstrip("0"),
    }
    for candidate in list(candidates):
        if candidate and candidate in mapping:
            return mapping[candidate]
    return None


def _lookup_plu_from_csv(code: str) -> str | None:
    cleaned = _normalize_code(code)
    if not cleaned:
        return None
    digits = "".join(ch for ch in cleaned if ch.isdigit())
    normalized_digits = _normalize_plu_value(digits)
    if normalized_digits:
        return normalized_digits
    mapped = _get_mapped_plu(cleaned)
    if mapped:
        return mapped
    return _normalize_plu_value(cleaned)


def _decode_uploaded_file(uploaded_file) -> str:
    raw = uploaded_file.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _normalize_code(code: str) -> str:
    code = (code or "").strip()
    return code


def _find_product_by_code(code: str, cache: dict[str, Product]) -> Product | None:
    cleaned = _normalize_code(code)
    if not cleaned:
        return None
    if cleaned in cache:
        return cache[cleaned]

    mapped_plu = _get_mapped_plu(cleaned)
    digits_plu = _lookup_plu_from_csv(cleaned)
    stripped = cleaned.lstrip("0")
    reference_query = Q()
    if cleaned:
        escaped = re.escape(cleaned)
        pattern = rf"(^|;)\s*{escaped}\s*(;|$)"
        reference_query = Q(reference__iregex=pattern)
    stripped_reference_query = Q()
    if stripped and stripped != cleaned:
        escaped_stripped = re.escape(stripped)
        pattern_stripped = rf"(^|;)\s*{escaped_stripped}\s*(;|$)"
        stripped_reference_query = Q(reference__iregex=pattern_stripped)

    query = (
        Q(code__iexact=cleaned)
        | Q(gtin__iexact=cleaned)
        | Q(supplier_code__iexact=cleaned)
        | Q(integration_code__iexact=cleaned)
        | Q(plu_code__iexact=cleaned)
        | reference_query
    )
    if stripped and stripped != cleaned:
        query |= (
            Q(code__iexact=stripped)
            | Q(gtin__iexact=stripped)
            | Q(supplier_code__iexact=stripped)
            | Q(integration_code__iexact=stripped)
            | Q(plu_code__iexact=stripped)
            | stripped_reference_query
        )
    if mapped_plu:
        query |= Q(plu_code__iexact=mapped_plu)
    if digits_plu and digits_plu != mapped_plu:
        query |= Q(plu_code__iexact=digits_plu)

    product = Product.objects.filter(query).order_by("id").first()
    if not product and mapped_plu:
        product = Product.objects.filter(plu_code__iexact=mapped_plu).order_by("id").first()
    if not product and digits_plu:
        product = Product.objects.filter(plu_code__iexact=digits_plu).order_by("id").first()
    cache[cleaned] = product
    if stripped and stripped != cleaned:
        cache[stripped] = product
    return product


def _parse_collector_content(content: str) -> list[CollectorInventoryItem]:
    items_map = {}
    errors = []
    product_cache: dict[str, Product | None] = {}
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(";")]
        if len(parts) < 5:
            errors.append(f"Linha {line_number}: formato inválido. Esperado 5 colunas separadas por ';'.")
            continue
        codigo_raw, descricao, loja, local, quantidade_bruta = parts[:5]
        codigo = _normalize_code(codigo_raw)
        if not codigo:
            errors.append(f"Linha {line_number}: código do produto vazio.")
            continue
        if not loja:
            errors.append(f"Linha {line_number}: código da loja vazio.")
            continue
        if not local:
            errors.append(f"Linha {line_number}: código do local vazio.")
            continue

        sinal = 1
        qty_raw = quantidade_bruta.strip()
        if qty_raw.startswith("-"):
            sinal = -1
            qty_raw = qty_raw[1:]
        normalized = "".join(ch for ch in qty_raw if ch.isdigit())
        if normalized == "":
            quantidade = ZERO_DECIMAL
        else:
            try:
                quantidade = (Decimal(normalized) / COLLECTOR_QUANTITY_FACTOR) * sinal
            except Exception:
                errors.append(f"Linha {line_number}: quantidade inválida \"{quantidade_bruta}\".")
                continue
            quantidade = quantidade.quantize(Decimal("0.001"))

        mapped_plu = _lookup_plu_from_csv(codigo)
        product = None
        if mapped_plu:
            product = Product.objects.filter(plu_code__iexact=mapped_plu).order_by("id").first()
        if not product:
            product = _find_product_by_code(codigo, product_cache)
        resolved_description = (descricao or "")[:255]
        if not resolved_description and product:
            resolved_description = (product.name or product.description or "")[:255]

        if product and mapped_plu and product.plu_code != mapped_plu:
            product.plu_code = mapped_plu
            product.save(update_fields=["plu_code"])

        if mapped_plu:
            plu_code = mapped_plu
        elif product and product.plu_code:
            plu_code = product.plu_code
        else:
            plu_code = codigo

        grouping_key = (plu_code or codigo, loja, local)
        existing_item = items_map.get(grouping_key)
        if existing_item:
            existing_item.quantidade = (existing_item.quantidade + quantidade).quantize(Decimal("0.001"))
            if not existing_item.descricao and resolved_description:
                existing_item.descricao = resolved_description
            if not existing_item.product and product:
                existing_item.product = product
            continue

        items_map[grouping_key] = CollectorInventoryItem(
            codigo_produto=codigo[:20],
            descricao=resolved_description,
            product=product,
            loja=loja[:10],
            local=local[:10],
            quantidade=quantidade,
            plu_code=plu_code or "",
            contagens=[],
        )

    if errors:
        raise ValueError(" ".join(errors[:5]))
    if not items_map:
        raise ValueError("Nenhum item válido foi encontrado no arquivo informado.")
    return list(items_map.values())


@login_required
def inventory_list(request):
    current_quantity_expr = Coalesce(
        "items__final_quantity",
        "items__recount_quantity",
        "items__counted_quantity",
        "items__frozen_quantity",
    )
    adjustment_expr = ExpressionWrapper(
        current_quantity_expr - F("items__frozen_quantity"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )

    inventories = (
        Inventory.objects.all()
        .annotate(
            total_items=Count("items", distinct=True),
            total_difference=Sum(adjustment_expr, default=ZERO_DECIMAL),
        )
        .order_by("-created_at")
    )

    company = getattr(request, "company", None)
    if company:
        inventories = inventories.filter(company=company)

    context = {
        "inventories": inventories,
        "active_company": company,
    }
    return render(request, "estoque/inventory_list.html", context)


@login_required
def inventory_from_selection(request):
    if request.method != "POST":
        messages.error(request, "Selecione os produtos antes de criar o inventário.")
        return redirect("products:index")

    company = getattr(request, "company", None)
    if not company:
        messages.error(request, "Selecione uma empresa ativa para continuar.")
        return redirect("products:index")

    selected_ids = request.POST.getlist("product_ids") or request.POST.getlist("selected_ids")
    if not selected_ids:
        messages.error(request, "Nenhum produto selecionado para o inventário.")
        return redirect("products:index")

    products = list(
        Product.objects.filter(pk__in=selected_ids)
        .select_related("product_group", "product_subgroup")
        .order_by("name")
    )
    if not products:
        messages.warning(request, "Os produtos selecionados não foram encontrados.")
        return redirect("products:index")

    product_rows = [
        {
            "product": product,
            "stock": product.stock_for_company(company),
        }
        for product in products
    ]

    if request.POST.get("confirm") == "1":
        form = InventorySelectionForm(request.POST)
        if form.is_valid():
            inventory = Inventory.objects.create(
                name=form.cleaned_data["name"],
                notes=form.cleaned_data.get("notes", ""),
                created_by=request.user if request.user.is_authenticated else None,
                company=company,
            )
            selections = [
                InventorySelection(inventory=inventory, product=row["product"])
                for row in product_rows
            ]
            InventorySelection.objects.bulk_create(selections, ignore_conflicts=True)
            messages.success(
                request,
                f"Inventário \"{inventory.name}\" criado com {len(product_rows)} produto(s) selecionado(s).",
            )
            return redirect("estoque:inventory_detail", pk=inventory.pk)
    else:
        default_name = f"Inventário {timezone.localdate():%d/%m/%Y}"
        form = InventorySelectionForm(initial={"name": default_name})

    return render(
        request,
        "estoque/inventory_prepare.html",
        {
            "form": form,
            "products": product_rows,
            "selected_ids": selected_ids,
            "active_company": company,
        },
    )


@login_required
def inventory_create(request):
    company = getattr(request, "company", None)
    if not company:
        messages.error(request, "Selecione uma empresa ativa antes de criar o inventário.")
        return redirect("estoque:inventory_list")
    if request.method == "POST":
        form = InventoryForm(request.POST)
        if form.is_valid():
            inventory = form.save(commit=False)
            if not inventory.name:
                inventory.name = "Inventário"
            if request.user.is_authenticated:
                inventory.created_by = request.user
            inventory.company = company
            inventory.save()
            messages.success(request, "Inventário criado com sucesso.")
            return redirect("estoque:inventory_detail", pk=inventory.pk)
    else:
        form = InventoryForm()
    return render(request, "estoque/inventory_form.html", {"form": form})


@login_required
def inventory_detail(request, pk):
    inventory = get_object_or_404(Inventory, pk=pk)
    item_qs = inventory.items.select_related("product").order_by("product__name")

    if inventory.company and inventory.company not in getattr(request, "available_companies", []):
        messages.error(request, "Você não tem permissão para acessar o inventário desta empresa.")
        return redirect("estoque:inventory_list")

    if not inventory.company and getattr(request, "company", None):
        inventory.company = request.company
        inventory.save(update_fields=["company"])

    formset = None
    filter_form = None
    items = []
    preview_products = []
    preview_total = None
    has_manual_selection = inventory.selected_products.exists()
    active_company = inventory.company or getattr(request, "company", None)

    if inventory.status == Inventory.Status.DRAFT:
        if not has_manual_selection:
            if request.method == "POST" and request.POST.get("action") == "update_filters":
                filter_form = InventoryForm(request.POST, instance=inventory)
                if filter_form.is_valid():
                    filter_form.save()
                    messages.success(request, "Filtros atualizados. Inicie o inventário para congelar as quantidades.")
                    return redirect("estoque:inventory_detail", pk=inventory.pk)
            else:
                filter_form = InventoryForm(instance=inventory)
        else:
            active_company = inventory.company
        source_qs = inventory.get_source_products().select_related("product_group", "product_subgroup")
        preview_total = source_qs.count()
        raw_preview = list(source_qs[:200])
        preview_products = [
            {
                "product": product,
                "stock": product.stock_for_company(active_company),
            }
            for product in raw_preview
        ]
    elif inventory.status == Inventory.Status.IN_PROGRESS:
        if request.method == "POST" and request.POST.get("action") == "update_counts":
            formset = InventoryCountFormSet(request.POST, queryset=item_qs)
            if formset.is_valid():
                formset.save()
                messages.success(request, "Contagens atualizadas com sucesso.")
                return redirect("estoque:inventory_detail", pk=inventory.pk)
        else:
            formset = InventoryCountFormSet(queryset=item_qs)
        items = [form.instance for form in formset.forms]
    else:
        items = list(item_qs)

    totals = {
        "frozen": sum((item.frozen_quantity for item in items), ZERO_DECIMAL),
        "counted": sum((item.counted_quantity or ZERO_DECIMAL for item in items), ZERO_DECIMAL),
        "recount": sum((item.recount_quantity or ZERO_DECIMAL for item in items), ZERO_DECIMAL),
        "effective": sum((item.effective_quantity for item in items), ZERO_DECIMAL),
    }
    totals["difference"] = totals["effective"] - totals["frozen"]
    has_recount = any(item.recount_quantity is not None for item in items)
    has_items = inventory.status != Inventory.Status.DRAFT and bool(items)

    context = {
        "inventory": inventory,
        "items": items,
        "formset": formset,
        "filter_form": filter_form,
        "totals": totals,
        "preview_total": preview_total,
        "preview_products": preview_products,
        "has_manual_selection": has_manual_selection,
        "active_company": active_company,
        "has_recount": has_recount,
        "has_items": has_items,
    }
    return render(request, "estoque/inventory_detail.html", context)


@login_required
def inventory_export_csv(request, pk):
    inventory = get_object_or_404(Inventory, pk=pk)
    if inventory.company and inventory.company not in getattr(request, "available_companies", []):
        messages.error(request, "Você não tem permissão para acessar o inventário desta empresa.")
        return redirect("estoque:inventory_detail", pk=inventory.pk)
    if inventory.status == Inventory.Status.DRAFT:
        messages.error(request, "Inicie o inventário antes de exportar o lote.")
        return redirect("estoque:inventory_detail", pk=inventory.pk)

    items = list(
        inventory.items.select_related("product").order_by("product__name", "product__id")
    )
    if not items:
        messages.warning(request, "Nenhum item disponível para exportação.")
        return redirect("estoque:inventory_detail", pk=inventory.pk)

    safe_name = slugify(inventory.name) or f"lote-{inventory.pk}"
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="inventario_{inventory.pk}_{safe_name}.csv"'

    delimiter = ";"
    response.write("\ufeff")
    response.write(f"sep={delimiter}\n")
    writer = csv.writer(response, delimiter=delimiter)
    writer.writerow(INVENTORY_EXPORT_HEADERS)

    company_label = ""
    if inventory.company:
        company_label = inventory.company.trade_name or inventory.company.name or ""

    for item in items:
        product = item.product
        writer.writerow(
            [
                inventory.pk,
                inventory.name,
                company_label,
                item.pk,
                product.pk,
                product.code or "",
                product.name or "",
                product.reference or "",
                format_decimal(item.frozen_quantity),
                format_decimal(item.counted_quantity),
                format_decimal(item.recount_quantity),
                format_decimal(item.final_quantity),
            ]
        )
    return response


@login_required
def inventory_import(request, pk):
    inventory = get_object_or_404(Inventory, pk=pk)
    if inventory.company and inventory.company not in getattr(request, "available_companies", []):
        messages.error(request, "Você não tem permissão para acessar o inventário desta empresa.")
        return redirect("estoque:inventory_detail", pk=inventory.pk)
    if inventory.status == Inventory.Status.DRAFT:
        messages.error(request, "Inicie o inventário antes de importar contagens.")
        return redirect("estoque:inventory_detail", pk=inventory.pk)
    if inventory.status == Inventory.Status.CLOSED:
        messages.error(request, "Inventários encerrados não podem receber novas importações.")
        return redirect("estoque:inventory_detail", pk=inventory.pk)

    form = InventoryImportForm()
    if request.method == "POST":
        form = InventoryImportForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data["csv_file"]
            try:
                raw_bytes = uploaded_file.read()
                decoded = raw_bytes.decode("utf-8-sig")
            except UnicodeDecodeError:
                uploaded_file.seek(0)
                decoded = uploaded_file.read().decode("latin-1")

            if not decoded.strip():
                form.add_error("csv_file", "O arquivo enviado está vazio.")
            else:
                delimiter = ";"
                content = decoded
                if content.startswith("sep="):
                    header_line, _, remainder = content.partition("\n")
                    sep_value = header_line.split("=", 1)[-1].strip()
                    delimiter = {"comma": ",", ",": ",", "tab": "\t", "\\t": "\t", "\t": "\t"}.get(sep_value.lower(), ";")
                    content = remainder
                sample = content[:1024]
                try:
                    sniffed = csv.Sniffer().sniff(sample, delimiters=";,\t")
                    delimiter = sniffed.delimiter
                except csv.Error:
                    pass

                reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
                if not reader.fieldnames or "Item ID" not in reader.fieldnames:
                    form.add_error(
                        "csv_file",
                        'O arquivo CSV precisa conter a coluna "Item ID", gerada a partir da exportação do inventário.',
                    )
                else:
                    updates = []
                    errors = []
                    pending_rows = []
                    for line_number, row in enumerate(reader, start=2):
                        item_id_raw = (row.get("Item ID") or "").strip()
                        if not item_id_raw:
                            errors.append(f"Linha {line_number}: coluna \"Item ID\" vazia.")
                            continue
                        try:
                            item_id = int(item_id_raw)
                        except ValueError:
                            errors.append(f"Linha {line_number}: \"Item ID\" inválido ({item_id_raw}).")
                            continue

                        inventory_id_raw = (row.get("Inventário ID") or "").strip()
                        if inventory_id_raw and str(inventory.pk) != inventory_id_raw:
                            errors.append(
                                f"Linha {line_number}: inventário informado ({inventory_id_raw}) não corresponde ao lote atual."
                            )
                            continue

                        row_changes = {}
                        row_has_error = False
                        for column, field_name in INVENTORY_IMPORT_FIELD_MAP.items():
                            if column not in row:
                                continue
                            raw_value = (row.get(column) or "").strip()
                            if raw_value == "":
                                continue
                            parsed_value = parse_decimal(raw_value)
                            if parsed_value is None:
                                errors.append(
                                    f"Linha {line_number}: valor inválido \"{raw_value}\" para a coluna \"{column}\"."
                                )
                                row_has_error = True
                                break
                            row_changes[field_name] = parsed_value

                        if row_has_error or not row_changes:
                            continue

                        pending_rows.append((line_number, item_id, row_changes))

                    if pending_rows:
                        item_ids = {item_id for _, item_id, _ in pending_rows}
                        items_map = {
                            item.pk: item
                            for item in InventoryItem.objects.filter(inventory=inventory, pk__in=item_ids)
                        }
                        for line_number, item_id, row_changes in pending_rows:
                            item = items_map.get(item_id)
                            if not item:
                                errors.append(
                                    f"Linha {line_number}: item {item_id} não pertence a este inventário."
                                )
                                continue
                            updates.append((item, row_changes))

                    if updates:
                        with transaction.atomic():
                            for item, changes in updates:
                                for field, value in changes.items():
                                    setattr(item, field, value)
                                item.save(update_fields=list(changes.keys()))

                        updated_count = len(updates)
                        messages.success(
                            request,
                            f"{updated_count} item(s) tiveram contagens atualizadas a partir do arquivo.",
                        )

                        if errors:
                            sample_errors = "; ".join(errors[:5])
                            messages.warning(
                                request,
                                "Algumas linhas foram ignoradas: " + sample_errors + ("..." if len(errors) > 5 else ""),
                            )

                        if form.cleaned_data.get("close_inventory") and inventory.can_close():
                            try:
                                inventory.close_inventory(request.user)
                            except ValueError as exc:
                                messages.warning(
                                    request,
                                    f"As contagens foram importadas, mas não foi possível fechar o inventário: {exc}",
                                )
                            else:
                                messages.success(request, "Inventário encerrado com sucesso após a importação.")

                        return redirect("estoque:inventory_detail", pk=inventory.pk)

                    message = "Nenhuma linha com valores preenchidos foi encontrada no arquivo."
                    if errors:
                        message += " " + " ".join(errors[:3])
                    form.add_error("csv_file", message)

    return render(
        request,
        "estoque/inventory_import.html",
        {
            "inventory": inventory,
            "form": form,
            "can_close": inventory.can_close(),
            "expected_headers": INVENTORY_EXPORT_HEADERS,
        },
    )


@login_required
def inventory_collector(request):
    items_qs = (
        CollectorInventoryItem.objects.select_related("product")
        .order_by("loja", "local", "codigo_produto")
    )
    if items_qs.exists():
        product_cache: dict[str, Product | None] = {}
        updated_any = False
        for item in items_qs:
            mapped_plu = _lookup_plu_from_csv(item.codigo_produto)
            product = None
            if mapped_plu:
                product = Product.objects.filter(plu_code__iexact=mapped_plu).order_by("id").first()
            if not product:
                product = item.product or _find_product_by_code(item.codigo_produto, product_cache)
            update_fields: list[str] = []
            if product and item.product_id != product.pk:
                item.product = product
                update_fields.append("product")

            if product and not item.descricao:
                resolved_description = (product.name or product.description or "")[:255]
                if item.descricao != resolved_description:
                    item.descricao = resolved_description
                    update_fields.append("descricao")

            if not item.plu_code:
                candidate_plu = (
                    mapped_plu
                    or (product.plu_code if product else None)
                    or item.codigo_produto
                )
                if candidate_plu:
                    item.plu_code = candidate_plu
                    update_fields.append("plu_code")
                    if product and product.plu_code != candidate_plu:
                        product.plu_code = candidate_plu
                        product.save(update_fields=["plu_code"])
            if update_fields:
                update_fields.append("atualizado_em")
                item.save(update_fields=update_fields)
                updated_any = True

        if updated_any:
            items_qs = (
                CollectorInventoryItem.objects.select_related("product")
                .order_by("loja", "local", "codigo_produto")
            )
    totals = items_qs.aggregate(
        total=Count("id"),
        total_quantity=Coalesce(Sum("quantidade"), ZERO_DECIMAL),
        total_closed=Count("fechado_em", filter=Q(fechado_em__isnull=False)),
    )

    import_form = CollectorInventoryImportForm()
    formset = CollectorInventoryFormSet(queryset=items_qs)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save":
            formset = CollectorInventoryFormSet(request.POST, queryset=items_qs)
            if formset.is_valid():
                formset.save()
                messages.success(request, "Quantidades atualizadas com sucesso.")
                return redirect("estoque:inventory_collector")
        elif action == "import":
            import_form = CollectorInventoryImportForm(request.POST, request.FILES)
            if import_form.is_valid():
                arquivo = import_form.cleaned_data["arquivo"]
                try:
                    content = _decode_uploaded_file(arquivo)
                    items = _parse_collector_content(content)
                except ValueError as exc:
                    import_form.add_error("arquivo", str(exc))
                else:
                    with transaction.atomic():
                        CollectorInventoryItem.objects.all().delete()
                        CollectorInventoryItem.objects.bulk_create(items, batch_size=1000)
                    messages.success(request, f"{len(items)} item(s) importados com sucesso.")
                    return redirect("estoque:inventory_collector")
        elif action == "finalize":
            if not items_qs.exists():
                messages.warning(request, "Não há itens para encerrar.")
            else:
                with transaction.atomic():
                    for item in items_qs:
                        item.finalize()
                messages.success(request, "Inventário encerrado. Nenhum item ficou sem contagem (valor zero aplicado).")
            return redirect("estoque:inventory_collector")
        elif action == "clear":
            CollectorInventoryItem.objects.all().delete()
            messages.success(request, "Itens do coletor excluídos.")
            return redirect("estoque:inventory_collector")
        else:
            messages.error(request, "Ação inválida.")

    context = {
        "formset": formset,
        "import_form": import_form,
        "totals": totals,
        "has_items": items_qs.exists(),
    }
    return render(request, "estoque/inventory_collector.html", context)


@login_required
def inventory_collector_export(request):
    items = list(
        CollectorInventoryItem.objects.select_related("product")
        .order_by("loja", "local", "codigo_produto")
    )
    if not items:
        messages.warning(request, "Não há itens do coletor para exportar.")
        return redirect("estoque:inventory_collector")

    response = HttpResponse(content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="inventario_coletor.txt"'

    lines = []
    for item in items:
        counts = item.contagens or []
        if counts:
            total = sum(counts, ZERO_DECIMAL).quantize(Decimal("0.001"))
            if item.quantidade != total:
                item.quantidade = total
                item.save(update_fields=["quantidade", "atualizado_em"])
        else:
            if item.quantidade != ZERO_DECIMAL:
                item.quantidade = ZERO_DECIMAL
                item.save(update_fields=["quantidade", "atualizado_em"])
        codigo_raw = (item.codigo_produto or "").strip()[:20]
        codigo = codigo_raw[:13].rjust(13, "0")
        descricao_base = item.descricao or (item.product.name if item.product else "")
        descricao = (descricao_base or "").strip()[:15].ljust(15)
        loja_raw = (item.loja or "").strip()[:10]
        loja = loja_raw[:6].rjust(6, "0")
        local_raw = (item.local or "").strip()[:10]
        local = local_raw[:2].rjust(2, "0")
        quantidade = item.quantidade or ZERO_DECIMAL
        quantidade_scaled = (quantidade * COLLECTOR_QUANTITY_FACTOR).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        quantidade_str = f"{int(quantidade_scaled):015d}"
        line = f"{codigo} ;{descricao};{loja};{local};{quantidade_str}"
        lines.append(line)

    response.write("\n".join(lines))
    response.write("\n")
    return response


@login_required
@require_POST
def inventory_start(request, pk):
    inventory = get_object_or_404(Inventory, pk=pk)
    if inventory.company and inventory.company not in getattr(request, "available_companies", []):
        messages.error(request, "Você não tem permissão para iniciar inventário desta empresa.")
        return redirect("estoque:inventory_detail", pk=inventory.pk)
    if not inventory.company and getattr(request, "company", None):
        inventory.company = request.company
        inventory.save(update_fields=["company"])
    try:
        inventory.start_inventory(request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Inventário iniciado e quantidades congeladas.")
    return redirect("estoque:inventory_detail", pk=inventory.pk)


@login_required
@require_POST
def inventory_close(request, pk):
    inventory = get_object_or_404(Inventory, pk=pk)
    if inventory.company and inventory.company not in getattr(request, "available_companies", []):
        messages.error(request, "Você não tem permissão para fechar inventário desta empresa.")
        return redirect("estoque:inventory_detail", pk=inventory.pk)
    try:
        inventory.close_inventory(request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Inventário fechado e quantidades atualizadas.")
    return redirect("estoque:inventory_detail", pk=inventory.pk)
