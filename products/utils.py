import csv
import io
import traceback
from datetime import datetime
import uuid
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import unicodedata

from django.db import connection, transaction
from django.db.models import Q
from functools import lru_cache
from django.utils import timezone

from .models import (
    Brand,
    Category,
    Department,
    Product,
    ProductGroup,
    Supplier,
    UnitOfMeasure,
    Volume,
    ProductImage,
    ProdutoSync,
)
from core.utils.documents import only_digits

EXPORT_HEADERS = [
    'ID',
    'Código',
    'Descrição',
    'Descrição Curta',
    'Unidade',
    'NCM',
    'Origem',
    'Preço',
    'Preço de custo',
    'Estoque',
    'Situação',
    'Referência',
    'Cód. no fornecedor',
    'Fornecedor',
    'Marca',
    'Grupo de produtos',
    'Categoria do produto',
    'Departamento',
    'Volumes',
    'Unidade de Medida',
    'GTIN/EAN',
    'GTIN/EAN da Embalagem',
    'Descrição Complementar',
    'Descrição do Produto no Fornecedor',
    'Localização',
    'Itens p/ caixa',
    'Peso líquido (Kg)',
    'Peso bruto (Kg)',
    'Largura do produto',
    'Altura do Produto',
    'Profundidade do produto',
    'Informações Adicionais',
    'Código Pai',
    'Código Integração',
    'Grupo de Tags/Tags',
    'Tributos',
    'URL Imagens Externas',
    'Link Externo',
    'Produto Variação',
    'Tipo Produção',
    'Classe de enquadramento do IPI',
    'Código na Lista de Serviços',
    'Tipo do item',
    'CEST',
    'Clonar dados do pai',
    'Condição do Produto',
    'Frete Grátis',
    'Número FCI',
    'Vídeo',
    'Data Validade',
    'Custo base precificação',
    '% Despesas variáveis',
    '% Despesas fixas',
    '% Tributos',
    '% Margem desejada',
    'Markup calculado',
    'Preço sugerido',
]


def _normalize_token(token: str | None) -> str | None:
    if token is None:
        return None
    cleaned = str(token).strip()
    return cleaned or None


def split_reference_tokens(value: str | None) -> list[str]:
    if not value:
        return []
    parts = [part.strip() for part in re.split(r"[;,\|]", value)]
    return [p for p in parts if p]


def lookup_plu_for_codes(*codes: str) -> str | None:
    """Resolve PLU from vw_produtos_sync_preco_estoque for any of the provided codes."""
    normalized = [_normalize_token(code) for code in codes]
    normalized = [code for code in normalized if code]
    if not normalized:
        return None
    normalized = list(dict.fromkeys(normalized))
    if not normalized:
        return None
    key = tuple(normalized)
    return _lookup_plu_cached(key)


@lru_cache(maxsize=512)
def _lookup_plu_cached(key: tuple[str, ...]) -> str | None:
    codes = list(key)
    if not codes:
        return None
    placeholders = ", ".join(["%s"] * len(codes))
    sql = f"SELECT * FROM vw_produtos_sync_preco_estoque WHERE codigo IN ({placeholders}) LIMIT 1"
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, codes)
            row = cursor.fetchone()
            if not row:
                return None
            columns = [col[0].lower() for col in cursor.description]
            for idx, col_name in enumerate(columns):
                if "plu" in col_name:
                    raw = row[idx]
                    value = _normalize_token(raw)
                    if value:
                        return value
            return None
    except Exception:
        return None


def format_decimal(value):
    if value is None or value == '':
        return ''
    if isinstance(value, (int, float)):
        return str(value).replace('.', ',')
    if isinstance(value, Decimal):
        normalized = value.normalize()
        # avoid scientific notation
        as_str = format(normalized, 'f')
        return as_str.replace('.', ',')
    return str(value)


def format_bool(value):
    if value is None:
        return ''
    return 'Sim' if value else 'Não'


def format_date(value):
    if not value:
        return ''
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime('%d/%m/%Y')


def product_to_export_row(product):
    """Return a dict representing the product data using IMPORT/EXPORT headers."""
    get_name = lambda obj, attr='name': getattr(obj, attr) if obj else ''

    row = {
        'ID': product.id,
        'Código': product.code or '',
        'Descrição': product.name or '',
        'Descrição Curta': product.short_description or '',
        'Unidade': product.unit or '',
        'NCM': product.ncm or '',
        'Origem': product.origin or '',
        'Preço': format_decimal(product.price),
        'Preço de custo': format_decimal(product.cost_price),
        'Estoque': format_decimal(product.stock),
        'Situação': product.status or '',
        'Referência': product.reference or product.supplier_code or '',
        'Cód. no fornecedor': product.supplier_code or '',
        'Fornecedor': product.supplier or get_name(product.supplier_obj),
        'Marca': product.brand or get_name(product.brand_obj),
        'Grupo de produtos': get_name(product.product_group),
        'Categoria do produto': product.category or get_name(product.category_obj),
        'Departamento': product.department or get_name(product.department_obj),
        'Volumes': product.volumes or get_name(product.volumes_obj, 'description'),
        'Unidade de Medida': product.unit_of_measure or get_name(product.unit_of_measure_obj),
        'GTIN/EAN': product.gtin or '',
        'GTIN/EAN da Embalagem': product.gtin_package or '',
        'Descrição Complementar': product.complement_description or '',
        'Descrição do Produto no Fornecedor': product.supplier_description or '',
        'Localização': product.location or '',
        'Itens p/ caixa': format_decimal(product.items_per_box),
        'Peso líquido (Kg)': format_decimal(product.weight_net),
        'Peso bruto (Kg)': format_decimal(product.weight_gross),
        'Largura do produto': format_decimal(product.width),
        'Altura do Produto': format_decimal(product.height),
        'Profundidade do produto': format_decimal(product.depth),
        'Informações Adicionais': product.additional_info or '',
        'Código Pai': product.parent_code or '',
        'Código Integração': product.integration_code or '',
        'Grupo de Tags/Tags': product.tags or '',
        'Tributos': product.taxes or '',
        'URL Imagens Externas': product.external_images or '',
        'Link Externo': product.external_link or '',
        'Produto Variação': product.variation or '',
        'Tipo Produção': product.production_type or '',
        'Classe de enquadramento do IPI': product.ipi_class or '',
        'Código na Lista de Serviços': product.service_list_code or '',
        'Tipo do item': product.item_type or '',
        'CEST': product.cest or '',
        'Clonar dados do pai': format_bool(product.clone_parent),
        'Condição do Produto': product.condition or '',
        'Frete Grátis': format_bool(product.free_shipping),
        'Número FCI': product.fci_number or '',
        'Vídeo': product.video or '',
        'Data Validade': format_date(product.expiration_date),
        'Custo base precificação': format_decimal(product.pricing_base_cost),
        '% Despesas variáveis': format_decimal(product.pricing_variable_expense_percent),
        '% Despesas fixas': format_decimal(product.pricing_fixed_expense_percent),
        '% Tributos': format_decimal(product.pricing_tax_percent),
        '% Margem desejada': format_decimal(product.pricing_desired_margin_percent),
        'Markup calculado': format_decimal(product.pricing_markup_factor),
        'Preço sugerido': format_decimal(product.pricing_suggested_price),
    }
    return row


def parse_decimal(value):
    if value is None:
        return None
    v = str(value).strip()
    if v == '':
        return None
    v = v.replace('.', '').replace(',', '.') if ',' in v else v
    try:
        return Decimal(v)
    except InvalidOperation:
        return None


def normalize_str(s):
    if s is None:
        return None
    return ' '.join(str(s).strip().split())


DEFAULT_SEARCH_FIELDS = [
    'name',
    'code',
    'description',
    'gtin',
    'reference',
    'supplier_code',
]

BOUNDARY_SEPARATORS = [
    ' ',
    '\t',
    '\n',
    '-',
    '/',
    '.',
    ',',
    ';',
    ':',
    '(',
    ')',
    '[',
    ']',
    '{',
    '}',
    '_',
]


def _needs_token_boundary(part):
    """Return True when the fragment should match at word/token start."""
    if not part:
        return False
    if part.startswith('^'):
        return True
    return bool(re.match(r'^[0-9]+[a-z]+[a-z0-9]*$', part, re.IGNORECASE))


def _clean_search_part(part):
    """Strip helper prefixes used to control matching."""
    if part.startswith('^'):
        return part[1:]
    return part


def _build_contains_query(part, fields):
    query = Q()
    for field in fields:
        query |= Q(**{f'{field}__icontains': part})
    return query


def _build_boundary_query(part, fields, is_postgres):
    query = Q()
    if is_postgres:
        pattern = rf'(^|[^0-9A-Za-z]){re.escape(part)}'
        for field in fields:
            query |= Q(**{f'{field}__iregex': pattern})
        return query

    for field in fields:
        field_query = Q(**{f'{field}__istartswith': part})
        for sep in BOUNDARY_SEPARATORS:
            field_query |= Q(**{f'{field}__icontains': f'{sep}{part}'})
        query |= field_query
    return query


def filter_products_by_search(qs, query, *, fields=None):
    """Apply product search filtering supporting % wildcards like the main product list."""
    raw_query = (query or '').strip()
    if not raw_query:
        return qs

    is_postgres = connection.vendor == 'postgresql'
    fields = fields or DEFAULT_SEARCH_FIELDS

    parts = [p for p in re.split(r"[%\s]+", raw_query) if p]
    if not parts:
        return qs.filter(_build_contains_query(raw_query, fields))

    for part in parts:
        needs_boundary = _needs_token_boundary(part)
        clean_part = _clean_search_part(part)
        if not clean_part:
            continue
        if needs_boundary:
            qs = qs.filter(_build_boundary_query(clean_part, fields, is_postgres))
        else:
            qs = qs.filter(_build_contains_query(clean_part, fields))
    return qs


def _clean_ean(value):
    if value is None:
        return None
    ean = str(value).strip()
    if not ean or ean == '-':
        return None
    return ean[:100]


def _safe_name(value, fallback):
    text = (value or '').strip()
    if not text:
        text = fallback
    return (text or '')[:200]


def _decimal_or_zero(value):
    if value in (None, ''):
        return Decimal('0.00')
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal('0.00')


def mirror_products_from_sync(
    *,
    codes: list[str] | None = None,
    limit: int | None = None,
    update: bool = False,
    dry_run: bool = False,
    chunk_size: int = 500,
):
    """
    Create or update Product entries based on the ProdutoSync view.

    Returns a dict with keys: processed, created, updated, existing, invalid.
    When dry_run=True no database changes are persisted.
    """
    qs = ProdutoSync.objects.all().order_by('codigo')
    code_filter = None
    if codes:
        code_filter = [str(c).strip() for c in codes if c is not None]
        if code_filter:
            qs = qs.filter(codigo__in=code_filter)
    total_selected = qs.count()
    if limit:
        qs = qs[:limit]

    created = 0
    updated_count = 0
    existing = 0
    invalid = 0
    processed = 0
    cache: dict[str, Product | None] = {}

    with transaction.atomic():
        for sync in qs.iterator(chunk_size=chunk_size):
            processed += 1
            raw_code = (sync.codigo or '').strip()
            normalized_code = Product.normalize_code(raw_code)
            if not normalized_code:
                invalid += 1
                continue

            product = cache.get(normalized_code)
            if normalized_code not in cache:
                product = Product.objects.filter(code=normalized_code).first()
                cache[normalized_code] = product

            price_source = next(
                (val for val in (
                    getattr(sync, 'preco_normal', None),
                    getattr(sync, 'preco_promocional_1', None),
                    getattr(sync, 'preco_promocional_2', None),
                ) if val not in (None, '')),
                None,
            )
            price = _decimal_or_zero(price_source)
            stock = _decimal_or_zero(getattr(sync, 'estoque_disponivel', None))
            gtin = _clean_ean(getattr(sync, 'ean', None))
            supplier_code = (getattr(sync, 'referencia', None) or raw_code or normalized_code)[:200]
            name = _safe_name(getattr(sync, 'descricao', None), normalized_code)
            description = (getattr(sync, 'descricao', None) or '').strip()
            cost_source = getattr(sync, 'custo', None)
            cost_value = None
            if cost_source not in (None, ''):
                cost_value = _decimal_or_zero(cost_source)
            effective_cost = cost_value if cost_value is not None else price_source

            if product is None:
                cost_price_value = effective_cost
                timestamp = timezone.now() if cost_price_value not in (None, '') else None
                product = Product(
                    code=normalized_code,
                    name=name,
                    description=description,
                    price=price,
                    cost_price=cost_price_value,
                    cost_price_updated_at=timestamp,
                    stock=stock,
                    gtin=gtin,
                    supplier_code=supplier_code,
                    reference=normalized_code,
                    integration_code=supplier_code[:200],
                )
                if not dry_run:
                    product.save()
                cache[normalized_code] = product
                created += 1
            else:
                fields_to_update: list[str] = []
                if update:
                    if name and name != product.name:
                        product.name = name
                        fields_to_update.append('name')
                    if description != (product.description or ''):
                        product.description = description
                        fields_to_update.append('description')
                    if gtin != (product.gtin or None):
                        product.gtin = gtin
                        fields_to_update.append('gtin')
                    if price != product.price:
                        product.price = price
                        fields_to_update.append('price')
                    if effective_cost is not None and effective_cost != product.cost_price:
                        product.cost_price = effective_cost
                        product.cost_price_updated_at = timezone.now()
                        fields_to_update.extend(['cost_price', 'cost_price_updated_at'])
                    if stock != (product.stock or Decimal('0.00')):
                        product.stock = stock
                        fields_to_update.append('stock')
                    if supplier_code != (product.supplier_code or ''):
                        product.supplier_code = supplier_code
                        fields_to_update.append('supplier_code')
                    if supplier_code != (product.integration_code or ''):
                        product.integration_code = supplier_code
                        fields_to_update.append('integration_code')
                    if normalized_code != (product.reference or None):
                        product.reference = normalized_code
                        fields_to_update.append('reference')

                    if fields_to_update:
                        if not dry_run:
                            product.save(update_fields=list(dict.fromkeys(fields_to_update)))
                        updated_count += 1
                    else:
                        existing += 1
                else:
                    existing += 1

        if dry_run:
            transaction.set_rollback(True)

    return {
        'processed': processed,
        'created': created,
        'updated': updated_count,
        'existing': existing,
        'invalid': invalid,
        'selected': total_selected if limit is None else min(total_selected, limit),
    }


def parse_date(value):
    if not value:
        return None
    v = str(value).strip()
    if v == '':
        return None
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    # fallback: find first dd/mm/YYYY-like substring
    m = re.search(r'(\d{2}[/-]\d{2}[/-]\d{4})', v)
    if m:
        try:
            return datetime.strptime(m.group(1).replace('-', '/'), '%d/%m/%Y').date()
        except Exception:
            return None
    return None


@transaction.atomic
def import_products_from_file(file_like, mapping=None, *, progress_key: str | None = None, dry_run: bool = False):
    """Import products from a file-like object (CSV, delimiter=';').
    Returns (created, updated, messages)
    """
    created = 0
    updated = 0
    messages = []
    # file_like can be path or file object (bytes or text). Ensure text mode for csv.
    if isinstance(file_like, (str, Path)):
        # Tolerant decoding: aceita UTF-8 com BOM e bytes inválidos sem quebrar
        fh = open(file_like, 'r', newline='', encoding='utf-8', errors='ignore')
        close_after = True
    else:
        # Try to rewind to start (ignore failures)
        try:
            file_like.seek(0)
        except Exception:
            pass
        # Peek a small sample to detect bytes vs str
        sample = None
        try:
            sample = file_like.read(1)
        except Exception:
            sample = None
        finally:
            try:
                file_like.seek(0)
            except Exception:
                pass

        if isinstance(sample, (bytes, bytearray)):
            # Wrap bytes stream into a text wrapper (UTF-8 with BOM, tolerando erros)
            fh = io.TextIOWrapper(file_like, encoding='utf-8-sig', errors='ignore', newline='')
            close_after = True  # close the wrapper when done
        else:
            fh = file_like
            close_after = False

    try:
        # Read full text to allow delimiter sniffing and optional BOM/separator line handling
        text = fh.read()
        # Excel sometimes writes a first line like: sep=;
        lines = text.splitlines()
        sep_declared = None
        if lines and lines[0].lower().startswith('sep=') and len(lines[0]) >= 5:
            sep_declared = lines[0][4:5]
            lines = lines[1:]
            text = "\n".join(lines)

        # Try sniffing delimiter from sample
        sample = "\n".join(lines[:10])
        delimiter = sep_declared or ';'
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=';,\t')
            delimiter = dialect.delimiter or delimiter
        except Exception:
            # fallback based on counts
            counts = {d: sample.count(d) for d in (';', ',', '\t')}
            delimiter = max(counts, key=lambda k: counts[k]) if any(counts.values()) else delimiter

        # Build reader from normalized text
        fh2 = io.StringIO(text)
        reader = csv.DictReader(fh2, delimiter=delimiter)
        total = 0

        def set_progress(processed=0, created_v=None, updated_v=None, done=False, last_error=None, **extra):
            if not progress_key:
                return
            key = f"products:import:{progress_key}"
            state = cache.get(key) or {}
            state.update({
                'total': total,
                'processed': processed,
                'created': created if created_v is None else created_v,
                'updated': updated if updated_v is None else updated_v,
                'done': done,
            })
            if last_error:
                errs = list(state.get('errors') or [])
                errs.append(last_error)
                # cap errors list to last 50
                state['errors'] = errs[-50:]
            if extra:
                state.update(extra)
            cache.set(key, state, 60 * 30)

        # Basic header validation before processing rows
        headers = reader.fieldnames or []
        if not headers:
            msg = 'Erro: arquivo CSV vazio ou sem cabeçalho.'
            messages.append(msg)
            set_progress(processed=0, done=True, last_error=msg, delimiter=delimiter)
            return created, updated, messages

        def normalize_header_key(value):
            if value is None:
                return ''
            value = unicodedata.normalize('NFKD', str(value).strip())
            value = ''.join(ch for ch in value if not unicodedata.combining(ch))
            return value.lower()

        normalized_headers = {}
        for h in headers:
            key = normalize_header_key(h)
            if key and key not in normalized_headers:
                normalized_headers[key] = h

        mapping_lookup = {}
        if mapping:
            for field, column in mapping.items():
                if not column:
                    continue
                col_key = normalize_header_key(column)
                mapping_lookup[field] = col_key

        missing_mapped_columns = [
            column for column in (mapping or {}).values()
            if column and normalize_header_key(column) not in normalized_headers
        ]

        if missing_mapped_columns:
            cols = ', '.join(sorted(set(missing_mapped_columns)))
            msg = f'Erro: coluna(s) mapeadas não encontradas no CSV: {cols}.'
            messages.append(msg)
            set_progress(processed=0, done=True, last_error=msg, headers=headers, delimiter=delimiter)
            return created, updated, messages

        price_column_present = (
            any(key in normalized_headers for key in ('preco', 'price'))
            or ('price' in mapping_lookup)
        )
        has_code_or_name = (
            any(key in normalized_headers for key in ('codigo', 'code'))
            or ('code' in mapping_lookup)
            or any(key in normalized_headers for key in ('descricao', 'descricao do produto no fornecedor', 'name'))
            or ('name' in mapping_lookup)
        )

        if not has_code_or_name:
            msg = 'Erro: é necessário ter ao menos "Código" ou "Descrição" no CSV.'
            messages.append(msg)
            set_progress(processed=0, done=True, last_error=msg, headers=headers, delimiter=delimiter)
            return created, updated, messages

        # Materialize rows to compute total for progress reporting
        rows = list(reader)
        total = len(rows)

        processed = 0
        set_progress(processed=0, headers=headers, delimiter=delimiter)

        def column_present(row_data, *columns):
            return any(col in row_data for col in columns)

        def raw_value(row_data, *columns):
            for col in columns:
                if col in row_data:
                    return row_data.get(col)
            return None

        def raw_text(row_data, *columns):
            value = raw_value(row_data, *columns)
            if value is None:
                return None
            return str(value)

        for idx, row in enumerate(rows, start=2):  # start=2 accounts for header line
            line_no = idx
            if mapping:
                for field, column in mapping.items():
                    value = row.get(column)
                    if field == 'code':
                        row['Código'] = value
                        row['Codigo'] = value
                        row['Código '] = value
                    elif field == 'name':
                        row['Descrição'] = value
                        row['Descricao'] = value
                        row['Descrição do Produto no Fornecedor'] = value
                    elif field == 'price':
                        row['Preço'] = value
                        row['Preco'] = value
                    elif field == 'short_description':
                        row['Descrição Curta'] = value
                    elif field == 'unit':
                        row['Unidade'] = value
                    elif field == 'ncm':
                        row['NCM'] = value
                    elif field == 'origin':
                        row['Origem'] = value
                    elif field == 'stock':
                        row['Estoque'] = value
                    elif field == 'cost_price':
                        row['Preço de custo'] = value
                        row['Preco de custo'] = value
                    elif field == 'supplier':
                        row['Fornecedor'] = value
                    elif field == 'location':
                        row['Localização'] = value
                    elif field == 'gtin':
                        row['GTIN/EAN'] = value
                    elif field == 'external_images':
                        row['URL Imagens Externas'] = value
                    elif field == 'category':
                        row['Categoria do produto'] = value
                    elif field == 'department':
                        row['Departamento'] = value
                    elif field == 'volumes':
                        row['Volumes'] = value
                    elif field == 'unit_of_measure':
                        row['Unidade de Medida'] = value
                    elif field == 'expiration_date':
                        row['Data Validade'] = value
            code_present = column_present(row, 'Código', 'Codigo', 'Código ')
            code = raw_value(row, 'Código', 'Codigo', 'Código ')
            if code is None and code_present:
                code = raw_text(row, 'Código', 'Codigo', 'Código ')
            name_present = column_present(row, 'Descrição', 'Descricao', 'Descrição do Produto no Fornecedor')
            name = raw_value(row, 'Descrição', 'Descricao', 'Descrição do Produto no Fornecedor')
            if not name:
                name = f"Produto {row.get('ID') or ''}".strip()

            # Row-level validation
            if not (code or (name and name.strip())):
                msg = f"Erro linha {line_no}: informe 'Código' ou 'Descrição'. Linha ignorada."
                messages.append(msg)
                set_progress(processed=processed, last_error=msg)
                continue

            price_raw = raw_value(row, 'Preço', 'Preco')
            price_val = None
            if price_raw not in (None, ''):
                price_val = parse_decimal(price_raw)
                if price_val is None:
                    msg = f"Erro linha {line_no}: preço inválido ({price_raw!r}). Linha ignorada."
                    messages.append(msg)
                    set_progress(processed=processed, last_error=msg)
                    continue

            group_name = row.get('Grupo de produtos') or row.get('Grupo de produtos ')
            brand = row.get('Marca')

            group = None
            if group_name:
                group_name_norm = normalize_str(group_name)
                group, _ = ProductGroup.objects.get_or_create(name=group_name_norm)

            # create/associate related objects
            brand_obj = None
            if brand:
                brand_norm = normalize_str(brand)
                brand_obj, _ = Brand.objects.get_or_create(name=brand_norm)

            supplier_name = row.get('Fornecedor')
            supplier_obj = None
            if supplier_name:
                supplier_norm = normalize_str(supplier_name)
                supplier_document_raw = (
                    row.get('CNPJ do fornecedor') or
                    row.get('Documento do fornecedor') or
                    row.get('Documento fornecedor') or
                    row.get('Documento Fornecedor') or
                    row.get('CNPJ Fornecedor') or
                    row.get('CNPJ fornecedor')
                )
                supplier_document_digits = only_digits(supplier_document_raw)
                if supplier_document_digits:
                    person_type = Supplier.PersonType.LEGAL if len(supplier_document_digits) == 14 else Supplier.PersonType.INDIVIDUAL
                    supplier_defaults = {
                        'name': supplier_norm,
                        'person_type': person_type,
                    }
                    supplier_obj, created = Supplier.objects.get_or_create(document=supplier_document_digits, defaults=supplier_defaults)
                    if not created:
                        updated = False
                        if supplier_norm and supplier_obj.name != supplier_norm:
                            supplier_obj.name = supplier_norm
                            updated = True
                        if supplier_obj.person_type != person_type:
                            supplier_obj.person_type = person_type
                            updated = True
                        if updated:
                            supplier_obj.save(update_fields=['name', 'person_type'])
                else:
                    supplier_obj = Supplier.objects.filter(name__iexact=supplier_norm).first()

            category_name = row.get('Categoria do produto')
            category_obj = None
            if category_name:
                category_norm = normalize_str(category_name)
                category_obj, _ = Category.objects.get_or_create(name=category_norm)

            department_name = row.get('Departamento')
            department_obj = None
            if department_name:
                department_norm = normalize_str(department_name)
                department_obj, _ = Department.objects.get_or_create(name=department_norm)

            volumes_name = row.get('Volumes')
            volumes_obj = None
            if volumes_name:
                volumes_norm = normalize_str(volumes_name)
                volumes_obj, _ = Volume.objects.get_or_create(description=volumes_norm)

            uom_name = row.get('Unidade de Medida')
            uom_obj = None
            if uom_name:
                uom_norm = normalize_str(uom_name)
                uom_obj, _ = UnitOfMeasure.objects.get_or_create(code=uom_norm)

            product = None
            # Normalize code to avoid duplicates caused by leading zeros or spacing
            code_norm = Product.normalize_code(code) if code else None
            if code_norm:
                product = Product.objects.filter(code=code_norm).first()
                if not product and code and code.strip() != code_norm:
                    # Also try the raw trimmed code for legacy records
                    product = Product.objects.filter(code=code.strip()).first()
            if not product:
                product = Product.objects.filter(name__iexact=name.strip()).first()

            if not product and price_val is None:
                msg = f"Erro linha {line_no}: informe um preço para novos produtos."
                messages.append(msg)
                set_progress(processed=processed, last_error=msg)
                continue

            display_name = (name or '').strip()
            if not display_name and product:
                display_name = product.name or ''
            if not display_name:
                display_name = f"Produto {code_norm or row.get('ID') or ''}".strip() or 'Produto'

            data = {}
            if code_norm is not None and (code_present or not product):
                data['code'] = code_norm
            if name_present or not product:
                data['name'] = display_name
            if price_val is not None:
                data['price'] = price_val

            decimal_field_map = {
                'fixed_ipi': ['Valor IPI fixo'],
                'stock': ['Estoque'],
                'cost_price': ['Preço de custo', 'Preco de custo'],
                'max_stock': ['Estoque máximo', 'Estoque maximo'],
                'min_stock': ['Estoque mínimo', 'Estoque minimo'],
                'weight_net': ['Peso líquido (Kg)'],
                'weight_gross': ['Peso bruto (Kg)'],
                'width': ['Largura do produto'],
                'height': ['Altura do Produto'],
                'depth': ['Profundidade do produto'],
                'items_per_box': ['Itens p/ caixa'],
                'icms_base_st': ['Valor base ICMS ST para retenção'],
                'icms_st_value': ['Valor ICMS ST para retenção'],
                'icms_substitute_value': ['Valor ICMS próprio do substituto'],
                'pricing_base_cost': ['Custo base precificação'],
                'pricing_variable_expense_percent': ['% Despesas variáveis'],
                'pricing_fixed_expense_percent': ['% Despesas fixas'],
                'pricing_tax_percent': ['% Tributos'],
                'pricing_desired_margin_percent': ['% Margem desejada'],
                'pricing_markup_factor': ['Markup calculado'],
                'pricing_suggested_price': ['Preço sugerido'],
            }
            for field, cols in decimal_field_map.items():
                if column_present(row, *cols):
                    data[field] = parse_decimal(raw_value(row, *cols))

            string_field_map = {
                'short_description': ['Descrição Curta'],
                'unit': ['Unidade'],
                'ncm': ['NCM'],
                'origin': ['Origem'],
                'status': ['Situação'],
                'supplier_code': ['Cód. no fornecedor'],
                'supplier': ['Fornecedor'],
                'location': ['Localização'],
                'supplier_description': ['Descrição do Produto no Fornecedor'],
                'complement_description': ['Descrição Complementar'],
                'variation': ['Produto Variação'],
                'production_type': ['Tipo Produção'],
                'ipi_class': ['Classe de enquadramento do IPI'],
                'service_list_code': ['Código na Lista de Serviços'],
                'item_type': ['Tipo do item'],
                'tags': ['Grupo de Tags/Tags'],
                'taxes': ['Tributos'],
                'parent_code': ['Código Pai'],
                'integration_code': ['Código Integração'],
                'brand': ['Marca'],
                'cest': ['CEST'],
                'volumes': ['Volumes'],
                'external_images': ['URL Imagens Externas', 'URL Imagens Externas '],
                'external_link': ['Link Externo'],
                'condition': ['Condição do Produto'],
                'fci_number': ['Número FCI'],
                'video': ['Vídeo'],
                'department': ['Departamento'],
                'unit_of_measure': ['Unidade de Medida'],
                'category': ['Categoria do produto'],
                'additional_info': ['Informações Adicionais'],
                'gtin': ['GTIN/EAN'],
                'gtin_package': ['GTIN/EAN da Embalagem'],
            }
            for field, cols in string_field_map.items():
                if column_present(row, *cols):
                    data[field] = raw_value(row, *cols)

            reference_columns = ['Referência', 'Referencia', 'Cód. no fornecedor']
            if column_present(row, *reference_columns):
                reference_val = raw_value(row, *reference_columns)
                data['reference'] = Product.normalize_code(reference_val) if reference_val else None

            if column_present(row, 'Clonar dados do pai'):
                data['clone_parent'] = True if (raw_text(row, 'Clonar dados do pai') or '').strip().upper() in ('SIM', 'S', '1', 'TRUE') else False
            if column_present(row, 'Frete Grátis'):
                data['free_shipping'] = True if (raw_text(row, 'Frete Grátis') or '').strip().upper() in ('SIM', 'S', '1', 'TRUE') else False

            if column_present(row, 'Data Validade', 'Data de Validade', 'Data Validade '):
                data['expiration_date'] = parse_date(
                    raw_value(row, 'Data Validade', 'Data de Validade', 'Data Validade ')
                )

            if group:
                data['product_group'] = group

            if brand_obj:
                data['brand_obj'] = brand_obj

            if supplier_obj:
                data['supplier_obj'] = supplier_obj

            if category_obj:
                data['category_obj'] = category_obj

            if department_obj:
                data['department_obj'] = department_obj

            if volumes_obj:
                data['volumes_obj'] = volumes_obj

            if uom_obj:
                data['unit_of_measure_obj'] = uom_obj

            if product:
                if not dry_run:
                    for k, v in data.items():
                        setattr(product, k, v)
                    product.calculate_pricing(force=True)
                    product.save()
                updated += 1
                messages.append(f"Atualizado produto: {display_name} (code={data.get('code') or product.code})")
            else:
                if not dry_run:
                    product = Product.objects.create(**data)
                created += 1
                messages.append(f"Criado produto: {display_name} (code={data.get('code') or code_norm})")

            # handle external images (comma, semicolon or pipe separated)
            images_field = row.get('URL Imagens Externas') or row.get('URL Imagens Externas ')
            if images_field and not dry_run:
                parts = re.split(r'[;,|]', images_field)
                for p in parts:
                    url = p.strip()
                    if not url:
                        continue
                    if not ProductImage.objects.filter(product=product, url=url).exists():
                        ProductImage.objects.create(product=product, url=url)
                        messages.append(f"Added image for {data['code']}: {url}")

            processed += 1
            set_progress(processed=processed)

    finally:
        if close_after:
            try:
                fh.detach()  # if TextIOWrapper over a bytes buffer
            except Exception:
                pass
            try:
                fh.close()
            except Exception:
                pass

    # mark done in progress
    if progress_key:
        st = cache.get(f"products:import:{progress_key}") or {}
        st.update({
            'total': locals().get('total', 0),
            'processed': locals().get('processed', 0),
            'created': created,
            'updated': updated,
            'done': True,
            'finished_at': datetime.utcnow().isoformat() + 'Z',
        })
        cache.set(f"products:import:{progress_key}", st, 60 * 30)

    return created, updated, messages


def start_import_task(data_bytes: bytes, *, mapping=None, dry_run: bool = False) -> str:
    """Start background import task and return progress key.
    The progress state is stored in Django cache under key 'products:import:<key>'.
    """
    key = uuid.uuid4().hex
    cache.set(f"products:import:{key}", {
        'total': 0,
        'processed': 0,
        'created': 0,
        'updated': 0,
        'errors': [],
        'done': False,
        'started_at': datetime.utcnow().isoformat() + 'Z',
        'file_size': len(data_bytes) if isinstance(data_bytes, (bytes, bytearray)) else None,
        'headers': [],
        'encoding': None,
        'attempts': [],
    }, 60 * 30)

    import threading
    from io import BytesIO

    def _runner():
        # 1) Tentativa padrão (UTF-8/UTF-8-SIG com tolerância)
        try:
            st = cache.get(f"products:import:{key}") or {}
            attempts = list(st.get('attempts') or [])
            attempts.append('utf-8-sig/errors=ignore')
            st['attempts'] = attempts
            st['encoding'] = 'utf-8'
            cache.set(f"products:import:{key}", st, 60 * 30)
            import_products_from_file(BytesIO(data_bytes), mapping=mapping, progress_key=key, dry_run=dry_run)
            return
        except UnicodeDecodeError:
            # will fallback
            pass
        except Exception as exc:
            # Se erro envolver decode de UTF-8, faremos fallback; caso contrário, registrar e sair
            msg = str(exc)
            if 'codec' not in msg and 'decode' not in msg and 'utf-8' not in msg:
                st = cache.get(f"products:import:{key}") or {}
                errs = list(st.get('errors') or [])
                tb = traceback.format_exc(limit=5)
                errs.append(f"Erro interno: {exc}\n{tb}")
                st['errors'] = errs[-50:]
                st['done'] = True
                st['finished_at'] = datetime.utcnow().isoformat() + 'Z'
                cache.set(f"products:import:{key}", st, 60 * 30)
                return

        # 2) Fallback para Latin-1/CP1252
        try:
            text = data_bytes.decode('latin-1')
            st = cache.get(f"products:import:{key}") or {}
            attempts = list(st.get('attempts') or [])
            attempts.append('latin-1/fallback')
            st['attempts'] = attempts
            st['encoding'] = 'latin-1'
            cache.set(f"products:import:{key}", st, 60 * 30)
            import_products_from_file(io.StringIO(text), mapping=mapping, progress_key=key, dry_run=dry_run)
            return
        except Exception as exc:
            st = cache.get(f"products:import:{key}") or {}
            errs = list(st.get('errors') or [])
            tb = traceback.format_exc(limit=5)
            errs.append(f"Erro interno (fallback latin-1): {exc}\n{tb}")
            st['errors'] = errs[-50:]
            st['done'] = True
            st['finished_at'] = datetime.utcnow().isoformat() + 'Z'
            cache.set(f"products:import:{key}", st, 60 * 30)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    return key
