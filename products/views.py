import base64
import re
import csv
from collections import Counter
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q, OuterRef, Subquery, F
from django.db import connection, transaction
from django.db.models.functions import Greatest, Coalesce
try:
    from django.contrib.postgres.search import TrigramSimilarity
except Exception:  # keeps compatibility when not using Postgres
    TrigramSimilarity = None
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.core.cache import cache
from django.core.paginator import EmptyPage, Paginator
from django.views.decorators.http import require_GET, require_POST
from fpdf import FPDF
import io
from datetime import datetime, date

from companies.models import Company
from companies.services import SefazAPIError, fetch_company_data_from_sefaz
from core.models import SefazConfiguration
from core.utils.documents import normalize_cnpj

from .forms import (
	ProductForm,
	ProductImportForm,
	SupplierForm,
	SupplierProductPriceForm,
	SupplierProductPriceImportForm,
	ProductGroupForm,
	ProductSubGroupForm,
	PriceAdjustmentForm,
	SupplierCatalogBulkForm,
	ProductStockFormSet,
)
from .models import (
	Product,
	ProductStock,
	Supplier,
	SupplierProductPrice,
	ProductGroup,
	ProductSubGroup,
	PriceAdjustmentBatch,
	PriceAdjustmentItem,
	PriceAdjustmentLog,
	ProdutoSync,
)
from .utils import (
    EXPORT_HEADERS,
    import_products_from_file,
    start_import_task,
    product_to_export_row,
    filter_products_by_search,
    mirror_products_from_sync,
    lookup_plu_for_codes,
    split_reference_tokens,
)

PRODUCTS_READ_ONLY_MSG = 'Catálogo é somente leitura aqui. Cadastre, altere ou remova produtos apenas no ERP (SysacME); esta aplicação só consulta a sincronização.'


def _reject_product_write(request):
	messages.error(request, PRODUCTS_READ_ONLY_MSG)
	return redirect('products:index')


def _sync_product_companies(product, selected_companies):
    selected_ids = set()
    if selected_companies:
        selected_ids = {company.pk for company in selected_companies}
    stock_ids = set(product.stock_entries.values_list('company_id', flat=True))
    final_ids = selected_ids | stock_ids
    if final_ids:
        product.companies.set(final_ids)
    else:
        product.companies.clear()


def index(request):
	# redireciona para a visão de produtos sincronizados (somente leitura)
	return redirect('products:sync_list')
	q = request.GET.get('q', '').strip()
	min_price = request.GET.get('min_price')
	max_price = request.GET.get('max_price')
	in_stock = request.GET.get('in_stock')
	has_image = request.GET.get('has_image')
	company_filter = request.GET.get('company')
	# sorting + pagination
	raw_sort = request.GET.get('sort')
	sort = (raw_sort or '').lower() or 'reference'
	raw_dir = (request.GET.get('dir') or '').lower()
	if raw_sort:
		dir_ = raw_dir or 'asc'
	else:
		# Default asc for reference listing; other sorts fall back below
		dir_ = raw_dir or ('asc' if sort == 'reference' else 'desc')
	try:
		page = int(request.GET.get('page') or 1)
	except Exception:
		page = 1
	# Preferred page size: from GET, then cookie, else default
	_per_page_src = request.GET.get('per_page') or request.COOKIES.get('pref_per_page')
	try:
		# Allow denser pages: default 50, up to 200
		per_page = max(1, min(200, int(_per_page_src or 50)))
	except Exception:
		per_page = 50

	# Dense (compact) table view toggle: GET overrides cookie
	if 'dense' in request.GET:
		dense_param = (request.GET.get('dense') or '').strip().lower()
		dense = dense_param in ('1', 'true', 'yes', 'y', 'on')
	else:
		dense_cookie = (request.COOKIES.get('pref_dense') or '').strip().lower()
		dense = dense_cookie in ('1', 'true', 'yes', 'y', 'on')

	if q:
		qs = filter_products_by_search(qs, q)
	if min_price:
		try:
			qs = qs.filter(price__gte=min_price)
		except Exception:
			pass
	if max_price:
		try:
			qs = qs.filter(price__lte=max_price)
		except Exception:
			pass
	if in_stock:
		qs = qs.filter(stock__gt=0)
	if has_image:
		qs = qs.filter(images__isnull=False).distinct()
	selected_company = None
	selected_company_obj = None
	if company_filter:
		try:
			selected_company = int(company_filter)
			qs = qs.filter(companies__id=selected_company).distinct()
			selected_company_obj = Company.objects.filter(pk=selected_company).first()
		except Exception:
			selected_company = None
			selected_company_obj = None

	# Ordenação e relevância (quando disponível)
	relevance_supported = bool(q and connection.vendor == 'postgresql' and TrigramSimilarity)
	if relevance_supported:
		try:
			qs = qs.annotate(
				score=TrigramSimilarity('name', q)
				+ TrigramSimilarity('description', q)
				+ TrigramSimilarity('code', q)
				+ TrigramSimilarity('gtin', q)
				+ TrigramSimilarity('reference', q)
				+ TrigramSimilarity('supplier_code', q)
			)
		except Exception:
			relevance_supported = False

	sort_fields = {
		'name': 'name',
		'code': 'code',
		'reference': 'reference',
		'price': 'price',
		'stock': 'stock',
		'created': 'created_at',
		'relevance': 'score',
	}
	# Se o usuário não informou sort e temos relevância, usar relevância
	if (not raw_sort) and relevance_supported:
		sort = 'relevance'
		if not raw_dir:
			dir_ = 'desc'
	if not dir_:
		dir_ = 'asc' if sort in ('reference', 'code', 'name') else 'desc'
	order_field = sort_fields.get(sort, 'created_at')
	if order_field == 'score' and not relevance_supported:
		order_field = 'created_at'
	if order_field == 'reference':
		qs = qs.annotate(_reference_sort=Coalesce('reference', 'supplier_code', 'code'))
		order_field = '_reference_sort'
	prefix = '' if dir_ == 'asc' else '-'
	if order_field == 'created_at':
		qs = qs.order_by(prefix + order_field)
	else:
		qs = qs.order_by(prefix + order_field, '-created_at')

	# Paginação
	paginator = Paginator(qs.prefetch_related('images'), per_page)
	try:
		page_obj = paginator.page(page)
	except EmptyPage:
		page_obj = paginator.page(paginator.num_pages)
	products = page_obj.object_list
	active_company = getattr(request, 'company', None)
	if active_company:
		stock_map = {
			entry['product_id']: entry['quantity']
			for entry in ProductStock.objects.filter(product__in=products, company=active_company).values('product_id', 'quantity')
		}
		for product in products:
			product.company_stock = stock_map.get(product.pk, Decimal('0.00'))
	else:
		for product in products:
			product.company_stock = product.stock if product.stock is not None else Decimal('0.00')
	try:
		row_start = page_obj.start_index()
	except Exception:
		row_start = 0
	context = {
		'products': products,
		'filters': {
			'q': q,
			'min_price': min_price or '',
			'max_price': max_price or '',
			'in_stock': bool(in_stock),
			'has_image': bool(has_image),
		},
		'total': paginator.count,
		'page_obj': page_obj,
		'is_paginated': paginator.num_pages > 1,
		'per_page': per_page,
		'per_page_options': [20, 50, 100, 200],
		'dense': dense,
		'sort': sort,
		'dir': dir_,
		'row_start': row_start,
		'companies': Company.objects.order_by('trade_name', 'name', 'id'),
		'selected_company': selected_company,
		'selected_company_obj': selected_company_obj,
		'active_company': active_company,
	}
	response = render(request, 'products/index.html', context)
	# Persist preferences in cookies when explicitly set via GET
	if 'per_page' in request.GET:
		response.set_cookie('pref_per_page', str(per_page), max_age=60*60*24*365)
	if 'dense' in request.GET:
		response.set_cookie('pref_dense', '1' if dense else '0', max_age=60*60*24*365)
	return response


@login_required
def sync_list(request):
	q = request.GET.get('q', '').strip()
	sort = (request.GET.get('sort') or 'codigo').lower()
	dir_ = (request.GET.get('dir') or 'desc').lower()
	page = request.GET.get('page') or 1
	_per_page = request.GET.get('per_page') or 50
	try:
		per_page = max(10, min(200, int(_per_page)))
	except Exception:
		per_page = 50

	reference_sq = Product.objects.filter(code=OuterRef('codigo')).values('reference')[:1]
	supplier_code_sq = Product.objects.filter(code=OuterRef('codigo')).values('supplier_code')[:1]

	qs = ProdutoSync.objects.all().annotate(
		reference=Coalesce(
			F('referencia'),
			Subquery(reference_sq),
			Subquery(supplier_code_sq),
			F('codigo'),
		)
	)
	loja_codigo = getattr(request, "loja_codigo", None)
	if loja_codigo:
		qs = qs.filter(loja=loja_codigo)
	if q:
		qs = filter_products_by_search(qs, q, fields=['codigo', 'descricao', 'ean', 'referencia', 'plu', 'reference'])

	sort_fields = {
		'codigo': 'codigo',
		'descricao': 'descricao',
		'ean': 'ean',
		'reference': 'reference',
		'referencia': 'referencia',
		'plu': 'plu',
		'preco': 'preco_normal',
		'preco_promocional_1': 'preco_promocional_1',
		'preco_promocional_2': 'preco_promocional_2',
		'estoque': 'estoque_disponivel',
		'loja': 'loja',
	}
	order_field = sort_fields.get(sort, 'codigo')
	order_prefix = '' if dir_ == 'asc' else '-'
	qs = qs.order_by(f'{order_prefix}{order_field}', 'codigo')

	paginator = Paginator(qs, per_page)
	page_obj = paginator.get_page(page)

	last_sync_at = None
	try:
		with connection.cursor() as cursor:
			cursor.execute("SELECT max(updated_at) FROM erp_produtos_sync")
			row = cursor.fetchone()
			if row:
				last_sync_at = row[0]
				if last_sync_at:
					last_sync_at = timezone.localtime(last_sync_at)
	except Exception:
		last_sync_at = None

	context = {
		'items': page_obj.object_list,
		'filters': {
			'q': q,
		},
		'page_obj': page_obj,
		'is_paginated': paginator.num_pages > 1,
		'per_page': per_page,
		'per_page_options': [25, 50, 100, 200],
		'sort': sort,
		'dir': dir_,
		'total': paginator.count,
		'last_sync_at': last_sync_at,
	}
	return render(request, 'products/sync_list.html', context)


@staff_member_required
@require_POST
def sync_apply(request):
	update_existing = (request.POST.get('update') or '').lower() in ('1', 'true', 'yes', 'on')
	dry_run = (request.POST.get('dry_run') or '').lower() in ('1', 'true', 'yes', 'on')
	try:
		result = mirror_products_from_sync(update=update_existing, dry_run=dry_run)
	except Exception as exc:
		messages.error(request, f'Falha ao espelhar produtos: {exc}')
		return redirect('products:sync_list')

	if dry_run:
		messages.info(
			request,
			f'Dry-run: {result["processed"]} registros analisados, '
			f'{result["created"]} criados, {result["updated"]} atualizados, '
			f'{result["existing"]} já existentes, {result["invalid"]} ignorados.',
		)
	else:
		messages.success(
			request,
			f'Sincronização concluída: {result["processed"]} registros processados, '
			f'{result["created"]} criados, {result["updated"]} atualizados, '
			f'{result["existing"]} já existentes, {result["invalid"]} ignorados.',
		)
	return redirect('products:sync_list')


def detail(request, pk):
    product = get_object_or_404(Product.objects.prefetch_related('images', 'companies'), pk=pk)
    company = getattr(request, 'company', None)
    profile = getattr(request.user, 'access_profile', None) if request.user.is_authenticated else None
    can_view_all = bool(profile and profile.can_view_all_companies)
    allowed_ids = {c.pk for c in getattr(request, 'available_companies', [])}
    product_companies = product.companies.order_by('trade_name', 'name')

    def _normalize_plu_display(value):
        if not value:
            return value
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        if digits:
            stripped = digits.lstrip("0")
            return stripped or "0"
        return str(value).strip()

    plu_code = _normalize_plu_display(product.plu_code)
    if not plu_code:
        candidates = [
            product.code,
            product.gtin,
            product.supplier_code,
            product.integration_code,
        ]
        candidates.extend(split_reference_tokens(product.reference))
        raw_plu = lookup_plu_for_codes(*candidates)
        plu_code = _normalize_plu_display(raw_plu)
        if plu_code and product.plu_code != plu_code:
            product.plu_code = plu_code
            product.save(update_fields=['plu_code'])

    if can_view_all:
        company_options = list(product_companies)
    else:
        company_options = [c for c in product_companies if c.pk in allowed_ids]
    if company and company not in company_options and (can_view_all or company.pk in allowed_ids):
        company_options.insert(0, company)
    return render(request, 'products/detail.html', {
        'product': product,
        'company_options': company_options,
        'active_company': company,
        'can_view_all_companies': can_view_all,
        'plu_code': plu_code,
    })


class ColumnMappingForm(forms.Form):
	mapping_json = forms.CharField(widget=forms.HiddenInput)


@staff_member_required
def import_preview(request):
	"""Two-step import: upload file -> preview rows and map columns -> import."""
	if request.method in ('GET', 'POST'):
		return _reject_product_write(request)
	if request.method == 'POST' and 'preview' in request.POST:
		form = ProductImportForm(request.POST, request.FILES)
		if form.is_valid():
			f = form.cleaned_data['csv_file']
			data = f.read()
			b64 = base64.b64encode(data).decode('ascii')
			request.session['import_csv_b64'] = b64
			# parse headers and first 5 rows (detect separator and handle 'sep=')
			text = data.decode('utf-8', errors='ignore')
			lines = text.splitlines()
			if lines and lines[0].lower().startswith('sep='):
				sep_decl = lines[0][4:5]
				lines = lines[1:]
			else:
				sep_decl = None
			sample = "\n".join(lines[:10])
			delimiter = sep_decl or ';'
			try:
				dialect = csv.Sniffer().sniff(sample, delimiters=';,\t')
				delimiter = dialect.delimiter or delimiter
			except Exception:
				pass
			reader = csv.reader(lines, delimiter=delimiter)
			headers = next(reader, [])
			preview = []
			for i, row in enumerate(reader):
				preview.append(row)
				if i >= 4:
					break
			mapping_form = ColumnMappingForm(initial={'mapping_json': ''})
			return render(request, 'products/import_preview.html', {'headers': headers, 'preview': preview, 'mapping_form': mapping_form})
	elif request.method == 'POST' and 'import' in request.POST:
		map_form = ColumnMappingForm(request.POST)
		if map_form.is_valid():
			mapping_json = map_form.cleaned_data['mapping_json']
			import json
			mapping = json.loads(mapping_json) if mapping_json else None
			# server-side validation of mapping
			if not mapping or 'price' not in mapping or (('code' not in mapping) and ('name' not in mapping)):
				messages.error(request, 'Mapeamento inválido: é necessário mapear o preço e pelo menos o código ou o nome.')
				return redirect('products:import_preview')
			b64 = request.session.get('import_csv_b64')
			if not b64:
				messages.error(request, 'No CSV in session. Please upload again.')
				return redirect('products:import_upload')
			data = base64.b64decode(b64)
			from io import BytesIO

			# execute import em background com progresso
			key = start_import_task(data, mapping=mapping, dry_run=False)
			# cleanup
			request.session.pop('import_csv_b64', None)
			return redirect('products:import_status', key=key)

	else:
		form = ProductImportForm()
	return render(request, 'products/import_upload.html', {'form': form})


@login_required
def create(request):
	return _reject_product_write(request)


@login_required
def update(request, pk):
	return _reject_product_write(request)


@login_required
def delete(request, pk):
	return _reject_product_write(request)


def report(request):
	total = Product.objects.count()
	avg_price = Product.objects.all().aggregate(Avg('price'))['price__avg']
	return render(request, 'products/report.html', {'total': total, 'avg_price': avg_price})


@login_required
def supplier_list(request, pk=None):
	if request.method == 'POST':
		return _reject_product_write(request)
	instance = None
	if pk is not None:
		instance = get_object_or_404(Supplier, pk=pk)
	form = SupplierForm(instance=instance)

	suppliers = Supplier.objects.all().order_by('name')
	try:
		config = SefazConfiguration.load()
	except Exception:
		config = None
	sefaz_configured = bool(config and config.base_url)
	return render(request, 'products/supplier_list.html', {
		'suppliers': suppliers,
		'form': form,
		'is_edit': instance is not None,
		'sefaz_configured': sefaz_configured,
	})


@login_required
def supplier_delete(request, pk):
	supplier = get_object_or_404(Supplier, pk=pk)
	if request.method == 'POST':
		name = supplier.name
		supplier.delete()
		messages.success(request, f'Fornecedor "{name}" removido.')
	return redirect('products:supplier_list')


def _parse_decimal(value):
	if value in (None, ''):
		return None
	if isinstance(value, (int, float, Decimal)):
		return Decimal(value)
	text = str(value).strip()
	if not text:
		return None
	text = text.replace('R$', '').replace('%', '').replace(' ', '').replace('.', '').replace(',', '.')
	try:
		return Decimal(text)
	except Exception:
		return None


def _parse_date(value):
	if value in (None, ''):
		return None
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	text = str(value).strip()
	if not text:
		return None
	for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
		try:
			return datetime.strptime(text, fmt).date()
		except ValueError:
			continue
	return None


def _format_decimal(value):
	if value in (None, ''):
		return ''
	try:
		return f"{Decimal(value):f}".replace('.', ',')
	except Exception:
		return str(value)


@login_required
def supplier_catalog(request, supplier_id):
	supplier = get_object_or_404(Supplier, pk=supplier_id)
	items = supplier.catalog_items.select_related('product').all().order_by('code', '-valid_from')
	initial = {}
	if request.GET.get('product'):
		try:
			initial_product = Product.objects.get(pk=request.GET['product'])
			initial = {
				'product': initial_product,
				'code': initial_product.code or initial_product.reference or initial_product.pk,
				'description': initial_product.name,
				'unit': initial_product.unit,
				'unit_price': initial_product.price,
				'replacement_cost': initial_product.cost_price,
			}
		except Product.DoesNotExist:
			pass
	add_form = SupplierProductPriceForm(initial=initial)
	import_form = SupplierProductPriceImportForm()

	if request.method == 'POST':
		action = request.POST.get('action') or 'add'
		if action == 'import':
			import_form = SupplierProductPriceImportForm(request.POST, request.FILES)
			if import_form.is_valid():
				file = import_form.cleaned_data['file']
				decoded = file.read().decode('utf-8-sig')
				reader = csv.DictReader(io.StringIO(decoded), delimiter=';')
				if not reader.fieldnames:
					messages.error(request, 'Arquivo vazio ou sem cabeçalho.')
					return redirect('products:supplier_catalog', supplier_id=supplier.pk)
				mapping = {
					'Código': 'code',
					'Descricao': 'description',
					'Descrição': 'description',
					'Unidade': 'unit',
					'Unid.': 'unit',
					'Qtd. etiq.': 'quantity',
					'Qtd. por embalagem': 'pack_quantity',
					'V. Unitário': 'unit_price',
					'Valor unitário': 'unit_price',
					'IPI (%)': 'ipi_percent',
					'Frete (%)': 'freight_percent',
					'ST (%)': 'st_percent',
					'Custo reposição': 'replacement_cost',
					'Início vigência': 'valid_from',
					'Fim vigência': 'valid_until',
				}
				created = 0
				updated = 0
				skipped = 0
				for row in reader:
					data = {}
					for key, value in row.items():
						if key is None:
							continue
						field = mapping.get(key.strip(), key.strip())
						data[field] = value
					code = (data.get('code') or '').strip()
					valid_from = _parse_date(data.get('valid_from'))
					if not code or not valid_from:
						skipped += 1
						continue
					defaults = {
						'description': data.get('description', '').strip(),
						'unit': data.get('unit', '').strip(),
						'quantity': _parse_decimal(data.get('quantity')),
						'pack_quantity': _parse_decimal(data.get('pack_quantity')),
						'unit_price': _parse_decimal(data.get('unit_price')) or Decimal('0'),
						'ipi_percent': _parse_decimal(data.get('ipi_percent')),
						'freight_percent': _parse_decimal(data.get('freight_percent')),
						'st_percent': _parse_decimal(data.get('st_percent')),
						'replacement_cost': _parse_decimal(data.get('replacement_cost')),
						'valid_until': _parse_date(data.get('valid_until')),
					}
					_, created_flag = SupplierProductPrice.objects.update_or_create(
						supplier=supplier,
						code=code,
						valid_from=valid_from,
						defaults=defaults,
					)
					if created_flag:
						created += 1
					else:
						updated += 1
				if created or updated:
					messages.success(
						request,
						f'Importação concluída: {created} criado(s), {updated} atualizado(s), {skipped} ignorado(s).'
					)
			else:
				messages.info(request, 'Nenhum item importado. Verifique os dados do arquivo.')
			return redirect('products:supplier_catalog', supplier_id=supplier.pk)
		else:
			add_form = SupplierProductPriceForm(request.POST)
			if add_form.is_valid():
				item = add_form.save(commit=False)
				item.supplier = supplier
				item.save()
				messages.success(request, f'Item {item.code} adicionado ao catálogo do fornecedor.')
				return redirect('products:supplier_catalog', supplier_id=supplier.pk)

	return render(request, 'products/supplier_catalog.html', {
		'supplier': supplier,
		'items': items,
		'add_form': add_form,
		'import_form': import_form,
	})


@login_required
def supplier_catalog_edit(request, supplier_id, item_id):
    return _reject_product_write(request)


@login_required
def supplier_catalog_delete(request, supplier_id, item_id):
	return _reject_product_write(request)


@login_required
def supplier_catalog_export(request, supplier_id):
	supplier = get_object_or_404(Supplier, pk=supplier_id)
	items = supplier.catalog_items.all().order_by('code', '-valid_from')
	response = HttpResponse(content_type='text/csv; charset=utf-8')
	filename = f'catalogo_fornecedor_{supplier_id}.csv'
	response['Content-Disposition'] = f'attachment; filename\"{filename}\"'
	writer = csv.writer(response, delimiter=';')
	writer.writerow([
		'Código',
		'Descrição',
		'Unidade',
		'Qtd. etiq.',
		'Qtd. por embalagem',
		'Valor unitário',
		'IPI (%)',
		'Frete (%)',
		'ST (%)',
		'Custo reposição',
		'Início vigência',
		'Fim vigência',
	])
	for item in items:
		writer.writerow([
			item.code,
			item.description,
			item.unit,
			_format_decimal(item.quantity),
			_format_decimal(item.pack_quantity),
			_format_decimal(item.unit_price),
			_format_decimal(item.ipi_percent),
			_format_decimal(item.freight_percent),
			_format_decimal(item.st_percent),
			_format_decimal(item.replacement_cost),
			item.valid_from.isoformat(),
			item.valid_until.isoformat() if item.valid_until else '',
		])
	return response


@login_required
def supplier_catalog_from_selection(request):
	if request.method != 'POST':
		messages.error(request, 'Selecione os produtos antes de vincular ao catálogo do fornecedor.')
		return redirect('products:index')

	selected_ids = request.POST.getlist('product_ids') or request.POST.getlist('selected_ids')
	if not selected_ids:
		messages.error(request, 'Nenhum produto foi selecionado.')
		return redirect('products:index')

	products = list(
		Product.objects.filter(pk__in=selected_ids)
		.select_related('product_group', 'product_subgroup')
		.order_by('name')
	)
	if not products:
		messages.warning(request, 'Os produtos selecionados não foram encontrados.')
		return redirect('products:index')

	if request.POST.get('confirm') == '1':
		form = SupplierCatalogBulkForm(request.POST)
		if form.is_valid():
			supplier = form.cleaned_data['supplier']
			valid_from = form.cleaned_data['valid_from']
			valid_until = form.cleaned_data.get('valid_until')
			created = 0
			updated = 0

			for product in products:
				code = product.code or product.reference or product.supplier_code or str(product.pk)
				defaults = {
					'product': product,
					'description': product.name,
					'unit': product.unit or '',
					'quantity': None,
					'pack_quantity': None,
					'unit_price': product.price or Decimal('0'),
					'ipi_percent': None,
					'freight_percent': None,
					'st_percent': None,
					'replacement_cost': product.cost_price,
					'valid_until': valid_until,
				}
				_, created_flag = SupplierProductPrice.objects.update_or_create(
					supplier=supplier,
					code=code,
					valid_from=valid_from,
					defaults=defaults,
				)
				if created_flag:
					created += 1
				else:
					updated += 1

			if created or updated:
				messages.success(
					request,
					f'{created} item(ns) incluído(s) e {updated} atualizado(s) para o fornecedor {supplier.name}.',
				)
			else:
				messages.info(request, 'Nenhum novo item foi criado ou atualizado.')
			return redirect('products:supplier_catalog', supplier_id=supplier.pk)
	else:
		form = SupplierCatalogBulkForm(initial={'valid_from': timezone.localdate()})

	return render(
		request,
		'products/supplier_catalog_bulk_add.html',
		{
			'form': form,
			'products': products,
			'selected_ids': selected_ids,
		},
	)


@login_required
def supplier_catalog_select(request, supplier_id):
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    q = (request.GET.get('q') or '').strip()
    products = Product.objects.all()
    if q:
        products = filter_products_by_search(products, q)
    products = products.order_by('name')[:200]

    if request.method == 'POST':
        return _reject_product_write(request)

    return render(request, 'products/supplier_catalog_select.html', {
        'supplier': supplier,
        'products': products,
        'query': q,
        'today': timezone.localdate(),
    })


@login_required
@require_GET
def supplier_sefaz_lookup(request):
	cnpj = (request.GET.get('cnpj') or '').strip()
	if not cnpj:
		return JsonResponse({'error': 'Informe o CNPJ.'}, status=400)
	try:
		data = fetch_company_data_from_sefaz(cnpj)
	except ValueError as exc:
		return JsonResponse({'error': str(exc)}, status=400)
	except SefazAPIError as exc:
		return JsonResponse({'error': str(exc)}, status=502)

	try:
		cnpj_digits = normalize_cnpj(data.get('tax_id') or cnpj)
	except ValueError:
		cnpj_digits = ''.join(ch for ch in (data.get('tax_id') or cnpj) if ch.isdigit())

	response_data = {
		'name': data.get('name') or '',
		'document': data.get('tax_id') or cnpj,
		'code': cnpj_digits,
		'person_type': Supplier.PersonType.LEGAL,
		'state_registration': data.get('state_registration') or '',
		'email': data.get('email') or '',
		'phone': data.get('phone') or '',
		'address': data.get('address') or '',
		'number': data.get('number') or '',
		'complement': data.get('complement') or '',
		'district': data.get('district') or '',
		'city': data.get('city') or '',
		'state': data.get('state') or '',
		'zip_code': data.get('zip_code') or '',
		'notes': data.get('notes') or '',
	}
	return JsonResponse({'data': response_data})


@login_required
def group_list(request, pk=None):
	instance = None
	if pk is not None:
		instance = get_object_or_404(ProductGroup, pk=pk)

	if request.method == 'POST':
		form = ProductGroupForm(request.POST, instance=instance)
		if form.is_valid():
			group = form.save()
			if instance:
				messages.success(request, f'Grupo "{group.name}" atualizado com sucesso.')
			else:
				messages.success(request, f'Grupo "{group.name}" cadastrado.')
			return redirect('products:group_list')
	else:
		form = ProductGroupForm(instance=instance)

	groups = ProductGroup.objects.select_related('parent_group').all().order_by('parent_group__name', 'name')
	return render(request, 'products/group_list.html', {
		'groups': groups,
		'form': form,
		'is_edit': instance is not None,
	})


@login_required
def group_delete(request, pk):
	group = get_object_or_404(ProductGroup, pk=pk)
	if request.method == 'POST':
		name = group.name
		group.delete()
		messages.success(request, f'Grupo "{name}" removido.')
	return redirect('products:group_list')


@login_required
def subgroup_list(request, pk=None):
	instance = None
	if pk is not None:
		instance = get_object_or_404(ProductSubGroup, pk=pk)

	if request.method == 'POST':
		form = ProductSubGroupForm(request.POST, instance=instance)
		if form.is_valid():
			subgroup = form.save()
			if instance:
				messages.success(request, f'Subgrupo "{subgroup.name}" atualizado com sucesso.')
			else:
				messages.success(request, f'Subgrupo "{subgroup.name}" cadastrado.')
			return redirect('products:subgroup_list')
	else:
		form = ProductSubGroupForm(instance=instance)

	subgroups = ProductSubGroup.objects.select_related('group', 'parent_subgroup').annotate(
		product_count=Count('products')
	).order_by('group__name', 'parent_subgroup__name', 'name')
	return render(request, 'products/subgroup_list.html', {
		'subgroups': subgroups,
		'form': form,
		'is_edit': instance is not None,
	})


@login_required
def subgroup_delete(request, pk):
	subgroup = get_object_or_404(ProductSubGroup, pk=pk)
	if request.method == 'POST':
		name = subgroup.name
		subgroup.delete()
		messages.success(request, f'Subgrupo "{name}" removido.')
	return redirect('products:subgroup_list')


@login_required
def export_products_csv(request):
	return_url = request.POST.get('return_url') or request.GET.get('return_url')
	if return_url and not url_has_allowed_host_and_scheme(return_url, allowed_hosts={request.get_host()}):
		return_url = None
	return_url = return_url or reverse('products:index')

	selected_ids = request.POST.getlist('product_ids')
	if request.method == 'POST':
		if not selected_ids:
			messages.error(request, 'Selecione ao menos um produto para exportar.')
			return redirect(return_url)
		products_qs = Product.objects.filter(pk__in=selected_ids).order_by('id')
	else:
		products_qs = Product.objects.all().order_by('id')

	products = list(products_qs)
	if request.method == 'POST' and not products:
		messages.warning(request, 'Os produtos selecionados não estão mais disponíveis.')
		return redirect(return_url)

	response = HttpResponse(content_type='text/csv; charset=utf-8')
	response['Content-Disposition'] = 'attachment; filename="produtos_export.csv"'
	# Permitir escolher separador via query (?sep=comma|semicolon|tab|,|;|\t)
	sep_param = (request.POST.get('sep') or request.GET.get('sep') or ';').lower()
	if sep_param in (',', 'comma', 'coma'):
		delimiter = ','
	elif sep_param in ('\t', 'tab', 't'):
		delimiter = '\t'
	else:
		delimiter = ';'

	# BOM para Excel + linha "sep=" ajuda programas a reconhecer o separador
	response.write('\ufeff')
	response.write(f"sep={delimiter}\n")
	writer = csv.DictWriter(response, fieldnames=EXPORT_HEADERS, delimiter=delimiter)
	writer.writeheader()
	for product in products:
		writer.writerow(product_to_export_row(product))
	return response


@login_required
def export_products_pdf(request):
	def _truncate(text, limit):
		text = text or ''
		return text if len(text) <= limit else text[: limit - 1] + '…'

	return_url = request.POST.get('return_url')
	if return_url and not url_has_allowed_host_and_scheme(return_url, allowed_hosts={request.get_host()}):
		return_url = None
	return_url = return_url or reverse('products:index')

	if request.method != 'POST':
		messages.error(request, 'Selecione os produtos desejados antes de gerar o PDF.')
		return redirect(return_url)

	selected_ids = request.POST.getlist('product_ids')
	if not selected_ids:
		messages.error(request, 'Selecione ao menos um produto para gerar o PDF.')
		return redirect(return_url)

	products_qs = Product.objects.filter(pk__in=selected_ids).order_by('name', 'id')
	products = list(products_qs)
	if not products:
		messages.warning(request, 'Os produtos selecionados não estão mais disponíveis.')
		return redirect(return_url)

	pdf = FPDF()
	pdf.set_auto_page_break(auto=True, margin=15)
	pdf.add_page()
	pdf.set_font('Helvetica', 'B', 16)
	pdf.cell(0, 10, 'Relatório de Produtos', ln=True)

	pdf.set_font('Helvetica', '', 12)
	now = timezone.localtime()
	pdf.cell(0, 8, f'Gerado em: {now.strftime("%d/%m/%Y %H:%M")}', ln=True)
	pdf.cell(0, 8, f'Total selecionado: {len(products)}', ln=True)
	pdf.ln(4)

	pdf.set_font('Helvetica', 'B', 11)
	pdf.set_fill_color(240, 240, 240)
	pdf.cell(18, 8, 'ID', border=1, fill=True)
	pdf.cell(38, 8, 'Código', border=1, fill=True)
	pdf.cell(62, 8, 'Produto', border=1, fill=True)
	pdf.cell(28, 8, 'Preço', border=1, fill=True)
	pdf.cell(28, 8, 'Estoque', border=1, fill=True)
	pdf.cell(0, 8, 'Referência', border=1, fill=True, ln=True)

	pdf.set_font('Helvetica', '', 10)
	for product in products:
		price = '-' if product.price is None else f'{product.price:.2f}'
		stock = '-' if product.stock is None else f'{product.stock:.2f}'
		pdf.cell(18, 8, str(product.pk), border=1)
		pdf.cell(38, 8, _truncate(product.code or '-', 18), border=1)
		pdf.cell(62, 8, _truncate(product.name, 36), border=1)
		pdf.cell(28, 8, price, border=1)
		pdf.cell(28, 8, stock, border=1)
		pdf.cell(0, 8, _truncate(product.reference or product.supplier_code or '-', 24), border=1, ln=True)

	response = HttpResponse(content_type='application/pdf')
	response['Content-Disposition'] = 'attachment; filename="produtos.pdf"'
	pdf_output = pdf.output(dest='S')
	if isinstance(pdf_output, str):
		pdf_bytes = pdf_output.encode('latin-1')
	else:
		pdf_bytes = bytes(pdf_output)
	response.write(pdf_bytes)
	return response


def _calc_margin(price, cost):
	if price in (None, Decimal('0')) or cost in (None, Decimal('0')):
		return None
	try:
		margin = ((price - cost) / price) * Decimal('100')
		return margin.quantize(Decimal('0.01'))
	except Exception:
		return None


def _compute_new_price(product, rule_type, params):
	old_price = product.price if product.price is not None else Decimal('0')
	cost = product.cost_price or product.pricing_base_cost
	if rule_type == PriceAdjustmentBatch.Rule.INCREASE_PERCENT:
		try:
			percent = Decimal(params.get('percent', '0'))
		except Exception:
			return None, PriceAdjustmentItem.Status.SKIPPED, 'Percentual inválido'
		if old_price == Decimal('0'):
			return None, PriceAdjustmentItem.Status.SKIPPED, 'Preço atual não informado'
		new_price = old_price * (Decimal('1') + (percent / Decimal('100')))
		return new_price.quantize(Decimal('0.01')), PriceAdjustmentItem.Status.PENDING, ''
	if rule_type == PriceAdjustmentBatch.Rule.SET_MARGIN:
		if cost in (None, Decimal('0')):
			return None, PriceAdjustmentItem.Status.SKIPPED, 'Custo não cadastrado'
		try:
			target_margin = Decimal(params.get('target_margin', '0'))
		except Exception:
			return None, PriceAdjustmentItem.Status.SKIPPED, 'Margem inválida'
		if target_margin >= Decimal('100'):
			return None, PriceAdjustmentItem.Status.SKIPPED, 'Margem precisa ser inferior a 100%'
		new_price = cost / (Decimal('1') - (target_margin / Decimal('100')))
		return new_price.quantize(Decimal('0.01')), PriceAdjustmentItem.Status.PENDING, ''
	return None, PriceAdjustmentItem.Status.SKIPPED, 'Regra não suportada'


@login_required
def price_adjustment_prepare(request):
	if request.method in ('GET', 'POST'):
		return _reject_product_write(request)
	if request.method != 'POST':
		messages.error(request, 'Selecione os produtos antes de abrir o reajuste.')
		return redirect('products:index')

	initial_ids = request.POST.getlist('product_ids') or request.POST.getlist('selected_ids')
	if not initial_ids:
		messages.error(request, 'Selecione ao menos um produto para o reajuste.')
		return redirect('products:index')

	products = list(Product.objects.filter(pk__in=initial_ids).order_by('name'))
	if not products:
		messages.warning(request, 'Os produtos selecionados não foram encontrados.')
		return redirect('products:index')

	product_rows = []
	for product in products:
		cost_value = product.cost_price or product.pricing_base_cost
		old_margin = _calc_margin(product.price, cost_value)
		product_rows.append({
			'product': product,
			'cost': cost_value,
			'old_price': product.price,
			'old_price_display': format(product.price, '.2f') if product.price is not None else '',
			'cost_display': format(cost_value, '.4f') if cost_value is not None else '',
			'old_margin': old_margin,
			'old_margin_display': format(old_margin, '.2f') if old_margin is not None else '',
			'new_price': None,
			'new_price_display': '',
			'new_margin': None,
			'new_margin_display': '',
			'difference': None,
			'difference_display': '',
			'difference_sign': 0,
			'margin_difference': None,
			'margin_difference_display': '',
			'margin_difference_sign': 0,
			'has_difference': False,
			'has_margin_difference': False,
			'status': None,
			'status_label': '',
			'message': '',
		})

	action = None
	if request.method == 'POST':
		if 'preview' in request.POST:
			action = 'preview'
		elif 'confirm' in request.POST:
			action = 'confirm'

	form = PriceAdjustmentForm()
	preview_ready = False
	status_labels_map = dict(PriceAdjustmentItem.Status.choices)
	if action in ('preview', 'confirm'):
		form = PriceAdjustmentForm(request.POST)
		if form.is_valid():
			params = form.get_parameters()
			for row in product_rows:
				product = row['product']
				new_price, status, message = _compute_new_price(product, form.cleaned_data['rule_type'], params)
				row['new_price'] = new_price
				row['new_price_display'] = format(new_price, '.2f') if new_price is not None else ''
				row['status'] = status
				row['status_label'] = status_labels_map.get(status, '')
				row['message'] = message
				row['new_margin'] = _calc_margin(new_price, row['cost']) if new_price else None
				row['new_margin_display'] = format(row['new_margin'], '.2f') if row['new_margin'] is not None else ''
				if new_price is not None and row['old_price'] is not None:
					diff = (new_price - row['old_price']).quantize(Decimal('0.01'))
					row['difference'] = diff
					row['difference_display'] = format(diff, '.2f')
					if diff > 0:
						row['difference_sign'] = 1
					elif diff < 0:
						row['difference_sign'] = -1
					else:
						row['difference_sign'] = 0
					row['has_difference'] = True
				else:
					row['difference'] = None
					row['difference_display'] = ''
					row['difference_sign'] = 0
					row['has_difference'] = False
				if row['new_margin'] is not None and row['old_margin'] is not None:
					margin_diff = (row['new_margin'] - row['old_margin']).quantize(Decimal('0.01'))
					row['margin_difference'] = margin_diff
					row['margin_difference_display'] = format(margin_diff, '.2f')
					if margin_diff > 0:
						row['margin_difference_sign'] = 1
					elif margin_diff < 0:
						row['margin_difference_sign'] = -1
					else:
						row['margin_difference_sign'] = 0
					row['has_margin_difference'] = True
				else:
					row['margin_difference'] = None
					row['margin_difference_display'] = ''
					row['margin_difference_sign'] = 0
					row['has_margin_difference'] = False
			preview_ready = True

			if action == 'confirm':
				if request.POST.get('preview_ready') != '1':
					messages.warning(request, 'Confira a prévia antes de confirmar a geração do lote.')
				else:
					batch = PriceAdjustmentBatch.objects.create(
						created_by=request.user,
						rule_type=form.cleaned_data['rule_type'],
						parameters=params,
						notes=form.cleaned_data.get('notes', ''),
					)

					success = 0
					skipped = 0
					for row in product_rows:
						product = row['product']
						new_price = row['new_price']
						status = row['status']
						message = row['message']
						if new_price is None and status == PriceAdjustmentItem.Status.PENDING:
							status = PriceAdjustmentItem.Status.SKIPPED
							message = message or 'Não foi possível calcular o novo preço.'
						if status == PriceAdjustmentItem.Status.PENDING:
							success += 1
						else:
							skipped += 1
						PriceAdjustmentItem.objects.create(
							batch=batch,
							product=product,
							status=status,
							message=message,
							old_price=row['old_price'],
							new_price=new_price,
							cost_value=row['cost'],
							old_margin_percent=row['old_margin'],
							new_margin_percent=row['new_margin'],
							rule_snapshot=params,
						)

					messages.success(
						request,
						f'Lote de reajuste #{batch.pk} criado com {success} itens e {skipped} pendências.',
					)
					return redirect('products:price_adjustment_detail', pk=batch.pk)
		else:
			preview_ready = False

	return render(request, 'products/price_adjustment_prepare.html', {
		'form': form,
		'products': products,
		'product_rows': product_rows,
		'selected_ids': initial_ids,
		'preview_ready': preview_ready,
	})


@login_required
def price_adjustment_detail(request, pk):
	if request.method in ('GET', 'POST'):
		return _reject_product_write(request)
	batch = get_object_or_404(
		PriceAdjustmentBatch.objects.select_related('created_by'),
		pk=pk,
	)
	items = list(batch.items.select_related('product'))

	if request.method == 'POST':
		allowed_actions = {
			PriceAdjustmentItem.Status.PENDING,
			PriceAdjustmentItem.Status.APPROVED,
			PriceAdjustmentItem.Status.REJECTED,
		}
		selected_ids = set()
		for raw_pk in request.POST.getlist('selected_items'):
			try:
				selected_ids.add(int(raw_pk))
			except (TypeError, ValueError):
				continue
		bulk_status = request.POST.get('bulk_status')
		if bulk_status not in allowed_actions:
			bulk_status = None
		bulk_apply = 'bulk_apply' in request.POST
		if bulk_apply and selected_ids and bulk_status is None:
			messages.error(request, 'Selecione uma ação para aplicar aos itens marcados.')
			return redirect('products:price_adjustment_detail', pk=batch.pk)

		changes = 0
		errors = 0
		with transaction.atomic():
			for item in items:
				product_before = item.product.price
				if item.pk in selected_ids and bulk_status:
					action = bulk_status
				else:
					field_name = f'status_{item.pk}'
					action = request.POST.get(field_name)
				if action not in allowed_actions:
					continue
				if action == item.status:
					continue

				if action == PriceAdjustmentItem.Status.APPROVED:
					if item.new_price is None:
						errors += 1
						messages.error(request, f'O item #{item.pk} não possui novo preço para aprovação.')
						continue
					try:
						item.apply_new_price()
					except ValueError as exc:
						errors += 1
						messages.error(request, str(exc))
						continue
					item.message = 'Preço aprovado.'
				else:
					# Restore previous price when leaving the approved state.
					if item.status == PriceAdjustmentItem.Status.APPROVED:
						item.revert_price()
					if action == PriceAdjustmentItem.Status.REJECTED:
						if not item.message or item.message == 'Preço aprovado.':
							item.message = 'Item rejeitado.'
					elif action == PriceAdjustmentItem.Status.PENDING:
						if item.message in ('Preço aprovado.', 'Item rejeitado.'):
							item.message = ''

				item.status = action
				item.save(update_fields=['status', 'message'])
				product_after = item.product.price

				if product_before != product_after:
					PriceAdjustmentLog.objects.create(
						item=item,
						batch=item.batch,
						product=item.product,
						action=action,
						decided_by=request.user if request.user.is_authenticated else None,
						old_price=product_before,
						new_price=product_after,
						notes=item.message,
					)

				changes += 1

		if changes:
			batch.refresh_status()
			messages.success(request, f'{changes} item(ns) atualizado(s) com sucesso.')
		elif errors == 0:
			messages.info(request, 'Nenhuma alteração foi aplicada.')
		return redirect('products:price_adjustment_detail', pk=batch.pk)

	status_counts = Counter(item.status for item in items)
	pending_count = status_counts.get(PriceAdjustmentItem.Status.PENDING, 0)
	approved_count = status_counts.get(PriceAdjustmentItem.Status.APPROVED, 0)
	rejected_count = status_counts.get(PriceAdjustmentItem.Status.REJECTED, 0)
	skipped_count = status_counts.get(PriceAdjustmentItem.Status.SKIPPED, 0)
	return render(request, 'products/price_adjustment_detail.html', {
		'batch': batch,
		'items': items,
		'pending_count': pending_count,
		'approved_count': approved_count,
		'rejected_count': rejected_count,
		'skipped_count': skipped_count,
	})


@login_required
def price_adjustment_history(request):
	limit = 200
	try:
		requested_limit = int(request.GET.get('limit', limit))
		if 0 < requested_limit <= 1000:
			limit = requested_limit
	except (TypeError, ValueError):
		pass
	logs = list(PriceAdjustmentLog.objects.select_related('product', 'batch', 'decided_by', 'item').order_by('-created_at')[:limit])
	return render(request, 'products/price_adjustment_history.html', {
		'logs': logs,
		'limit': limit,
	})



@staff_member_required
def import_upload(request):
	if request.method in ('GET', 'POST'):
		return _reject_product_write(request)
	if request.method == 'POST':
		form = ProductImportForm(request.POST, request.FILES)
		if form.is_valid():
			f = form.cleaned_data['csv_file']
			data = f.read()
			dry_run = bool(form.cleaned_data.get('dry_run'))
			key = start_import_task(data, mapping=None, dry_run=dry_run)
			return redirect('products:import_status', key=key)
	else:
		form = ProductImportForm()
	return render(request, 'products/import_upload.html', {'form': form})


@staff_member_required
def import_status(request, key: str):
	"""Render a simple page that polls import progress."""
	if request.method in ('GET', 'POST'):
		return _reject_product_write(request)
	return render(request, 'products/import_status.html', {'key': key})


@staff_member_required
def import_progress(request, key: str):
	if request.method in ('GET', 'POST'):
		return _reject_product_write(request)
	from django.core.cache import cache
	state = cache.get(f"products:import:{key}") or {'total': 0, 'processed': 0, 'created': 0, 'updated': 0, 'errors': [], 'done': True}
	return JsonResponse(state)


@staff_member_required
def import_errors_csv(request, key: str):
	if request.method in ('GET', 'POST'):
		return _reject_product_write(request)
	import csv, re
	state = cache.get(f"products:import:{key}") or {}
	errors = state.get('errors') or []
	resp = HttpResponse(content_type='text/csv; charset=utf-8')
	resp['Content-Disposition'] = f'attachment; filename="import_errors_{key}.csv"'
	w = csv.writer(resp, delimiter=';')
	w.writerow(['linha', 'mensagem'])
	for e in errors:
		m = re.match(r"Erro linha\s+(\d+):\s*(.*)", e)
		if m:
			w.writerow([m.group(1), m.group(2)])
		else:
			w.writerow(['', e])
	if not errors:
		w.writerow(['', 'Sem erros registrados'])
	return resp


@login_required
def delete_image(request, pk):
	if request.method in ('GET', 'POST'):
		return _reject_product_write(request)
	"""Delete a ProductImage and redirect back to the product edit page."""
	from .models import ProductImage
	img = get_object_or_404(ProductImage, pk=pk)
	product_pk = img.product.pk
	if request.method == 'POST':
		img.delete()
		messages.success(request, 'Imagem removida.')
		return redirect(resolve_url('products:update', pk=product_pk))
	return render(request, 'products/confirm_delete_image.html', {'image': img})

# Create your views here.
