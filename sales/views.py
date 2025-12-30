from decimal import Decimal
from datetime import timedelta
import unicodedata

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from fpdf import FPDF

from .forms import QuoteForm, QuoteItemFormSet, OrderForm, OrderItemFormSet, SalespersonForm
from .models import Quote, Order, OrderItem, Salesperson, Pedido, ItemPedido
from products.models import Product
from core.models import SalesConfiguration

UNICODE_LATIN_REPLACEMENTS = str.maketrans({
	'\u2014': '-',  # em dash
	'\u2013': '-',  # en dash
	'\u2012': '-',  # figure dash
	'\u2010': '-',  # hyphen
	'\u2011': '-',  # non-breaking hyphen
	'\u2212': '-',  # minus sign
	'\u00a0': ' ',  # non-breaking space
	'\u2022': '*',
	'\u2026': '...',
	'\u2018': "'",
	'\u2019': "'",
	'\u201c': '"',
	'\u201d': '"',
})


def _loja_codigo_candidates(loja_codigo: str | None) -> list[str]:
	value = (loja_codigo or '').strip()
	if not value:
		return []
	if not value.isdigit():
		return [value]
	stripped = value.lstrip('0') or '0'
	candidates = {
		value,
		stripped,
		value.zfill(5),
		value.zfill(6),
		stripped.zfill(5),
		stripped.zfill(6),
	}
	return [c for c in candidates if c]


def _filter_by_loja_codigo(queryset, loja_codigo: str | None):
	if not loja_codigo or not hasattr(queryset.model, 'loja_codigo'):
		return queryset
	candidates = _loja_codigo_candidates(loja_codigo)
	if not candidates:
		return queryset
	return queryset.filter(loja_codigo__in=candidates)


def _build_quote_item_metrics(items):
	total_quantity = Decimal('0')
	total_discount = Decimal('0')
	gross_total = Decimal('0')
	net_total = Decimal('0')
	cost_total = Decimal('0')
	metrics = {}

	for item in items:
		product = getattr(item, 'product', None)
		if not product:
			continue
		quantity = item.quantity or Decimal('0')
		unit_price = item.unit_price or Decimal('0')
		discount = item.discount or Decimal('0')
		line_gross = quantity * unit_price
		line_net = item.total_amount

		total_quantity += quantity
		total_discount += discount
		gross_total += line_gross
		net_total += line_net

		margin_percent = None
		cost_amount = None
		unit_label = ''
		code_label = ''
		if product:
			unit_label = product.unit or ''
			code_label = product.code or ''
			if product.cost_price is not None:
				cost_price = Decimal(product.cost_price)
				cost_amount = cost_price * quantity
				if unit_price:
					margin_percent = ((unit_price - cost_price) / unit_price) * Decimal('100')
		if cost_amount is not None:
			cost_total += cost_amount

		discount_percent = None
		if line_gross:
			discount_percent = (discount / line_gross) * Decimal('100') if discount else Decimal('0')

		metrics[item.pk] = {
			'unit': unit_label,
			'code': code_label,
			'total': line_net,
			'discount_percent': discount_percent,
			'has_discount_percent': discount_percent is not None,
			'margin_percent': margin_percent,
			'has_margin': margin_percent is not None,
		}

	overall_margin = None
	if gross_total > 0 and cost_total > 0:
		overall_margin = ((net_total - cost_total) / gross_total) * Decimal('100')

	discount_percent_total = None
	if gross_total > 0 and total_discount > 0:
		discount_percent_total = (total_discount / gross_total) * Decimal('100')

	summary = {
		'total_quantity': total_quantity,
		'total_discount': total_discount,
		'gross_total': gross_total,
		'net_total': net_total,
		'discount_percent': discount_percent_total,
		'overall_margin': overall_margin,
		'has_margin': overall_margin is not None,
		'has_discount_percent': discount_percent_total is not None,
	}
	return metrics, summary


def _get_sales_permissions(user):
	if not getattr(user, 'is_authenticated', False):
		return {'manage': False, 'create': False, 'edit': False, 'delete': False}
	if user.is_superuser or user.is_staff:
		return {'manage': True, 'create': True, 'edit': True, 'delete': True}
	profile = getattr(user, 'access_profile', None)
	if not profile:
		return {'manage': True, 'create': True, 'edit': True, 'delete': True}
	perms = profile.sales_permissions()
	return {
		'manage': perms.get('manage', False),
		'create': perms.get('create', False),
		'edit': perms.get('edit', False),
		'delete': perms.get('delete', False),
	}


def _ensure_can_manage_sales(request, action, redirect_to):
	perms = _get_sales_permissions(request.user)
	if not perms['manage'] or (action and not perms.get(action, False)):
		messages.error(request, 'Você não tem permissão para executar esta ação nas vendas.')
		return perms, redirect(redirect_to)
	return perms, None


def _apply_common_filters(queryset, request):
	q = (request.GET.get('q') or '').strip()
	status = (request.GET.get('status') or '').strip()
	company = getattr(request, 'company', None)
	loja_codigo = getattr(request, 'loja_codigo', None)
	if company and hasattr(queryset.model, 'company_id'):
		queryset = queryset.filter(company=company)
	queryset = _filter_by_loja_codigo(queryset, loja_codigo)
	if q:
		queryset = queryset.filter(
			Q(number__icontains=q) |
			Q(client__first_name__icontains=q) |
			Q(client__last_name__icontains=q) |
			Q(client__email__icontains=q)
		)
	if status:
		queryset = queryset.filter(status=status)
	return queryset, q, status


@login_required
def quote_list(request):
	qs = Quote.objects.select_related('client', 'salesperson__user').prefetch_related('items')
	qs, q, status = _apply_common_filters(qs, request)
	perms = _get_sales_permissions(request.user)
	context = {
		'quotes': qs,
		'filters': {
			'q': q,
			'status': status,
		},
		'status_choices': Quote.Status.choices,
 		'sales_permissions': perms,
	}
	return render(request, 'sales/quote_list.html', context)


@login_required
def quote_detail(request, pk):
	loja_codigo = getattr(request, 'loja_codigo', None)
	quote_qs = Quote.objects.select_related('client', 'salesperson__user').prefetch_related('items__product')
	quote_qs = _filter_by_loja_codigo(quote_qs, loja_codigo)
	quote = get_object_or_404(quote_qs, pk=pk)
	if quote.company and quote.company not in getattr(request, 'available_companies', []):
		messages.error(request, 'Você não tem permissão para acessar este orçamento.')
		return redirect('sales:quote_list')
	perms = _get_sales_permissions(request.user)
	quote_items = quote.items.filter(product__isnull=False).order_by('sort_order', 'pk')
	return render(request, 'sales/quote_detail.html', {
		'quote': quote,
		'sales_permissions': perms,
		'quote_items': quote_items,
	})


@login_required
def quote_pdf(request, pk):
	loja_codigo = getattr(request, 'loja_codigo', None)
	quote_qs = Quote.objects.select_related('client', 'company', 'salesperson__user').prefetch_related('items__product')
	if loja_codigo:
		quote_qs = quote_qs.filter(loja_codigo=loja_codigo)
	quote = get_object_or_404(quote_qs, pk=pk)
	if quote.company and quote.company not in getattr(request, 'available_companies', []):
		messages.error(request, 'Você não tem permissão para acessar este orçamento.')
		return redirect('sales:quote_list')

	def _latin(text):
		if text is None:
			return ''
		if not isinstance(text, str):
			text = str(text)
		text = text.translate(UNICODE_LATIN_REPLACEMENTS)
		try:
			return text.encode('latin-1', 'ignore').decode('latin-1')
		except UnicodeEncodeError:
			normalized = unicodedata.normalize('NFKD', text)
			return normalized.encode('latin-1', 'ignore').decode('latin-1')

	def _format_decimal(value, places=2, allow_blank=False):
		if value in (None, ''):
			return '' if allow_blank else '0,00'
		try:
			number = Decimal(value)
		except Exception:  # pragma: no cover - fallback conversion
			number = Decimal('0')
		format_str = f'{{0:.{places}f}}'.format(number)
		return format_str.replace('.', ',')

	def _format_currency(value):
		return f'R$ {_format_decimal(value, 2)}'

	def _format_date(value):
		if not value:
			return '-'
		return value.strftime('%d/%m/%Y')

	def _truncate(text, max_length):
		if not text:
			return ''
		text = str(text)
		return text if len(text) <= max_length else text[: max_length - 3] + '...'

	pdf = FPDF()
	pdf.set_auto_page_break(auto=True, margin=20)
	pdf.add_page()

	company = quote.company
	client = quote.client
	issue_date = timezone.localtime(quote.created_at).strftime('%d/%m/%Y')

	company_name = company.trade_name or company.name if company else ''
	if not company_name:
		company_name = 'Orçamento'

	pdf.set_font('Helvetica', 'B', 16)
	pdf.cell(0, 10, _latin(company_name), ln=True)

	pdf.set_font('Helvetica', '', 10)
	if company:
		if company.tax_id:
			pdf.cell(0, 6, _latin(f'CNPJ: {company.tax_id}'), ln=True)
		address_parts = [
			part for part in (
				company.address,
				company.number,
				company.district,
			) if part
		]
		city_state = ' - '.join(filter(None, [company.city, company.state])) if company.city or company.state else ''
		if address_parts:
			pdf.cell(0, 5, _latin(', '.join(address_parts)), ln=True)
		if city_state or company.zip_code:
			location_line = ' - '.join(part for part in [city_state, company.zip_code] if part)
			if location_line:
				pdf.cell(0, 5, _latin(location_line), ln=True)
		contact_parts = [part for part in (company.phone, company.email, company.website) if part]
		if contact_parts:
			pdf.cell(0, 5, _latin(' / '.join(contact_parts)), ln=True)

	pdf.ln(3)

	pdf.set_font('Helvetica', 'B', 12)
	if quote.number:
		pdf.cell(0, 7, _latin(f'Orçamento {quote.number}'), ln=True)
	else:
		pdf.cell(0, 7, 'Orçamento', ln=True)

	pdf.set_font('Helvetica', '', 10)
	pdf.cell(0, 6, _latin(f'Emissão: {issue_date}'), ln=True)
	pdf.cell(0, 6, _latin(f'Validade: {_format_date(quote.valid_until)}'), ln=True)
	pdf.cell(0, 6, _latin(f'Situação: {quote.get_status_display()}'), ln=True)
	if quote.salesperson:
		salesperson_user = getattr(quote.salesperson, 'user', None)
		if salesperson_user:
			name = salesperson_user.get_full_name() or salesperson_user.get_username()
		else:
			name = str(quote.salesperson)
		pdf.cell(0, 6, _latin(f'Vendedor: {name}'), ln=True)

	pdf.ln(4)

	pdf.set_font('Helvetica', 'B', 11)
	pdf.cell(0, 6, 'Cliente', ln=True)
	pdf.set_font('Helvetica', '', 10)
	if client:
		client_name = f'{client.first_name} {client.last_name}'.strip() or str(client)
		pdf.cell(0, 5, _latin(client_name), ln=True)
		document = getattr(client, 'formatted_document', '') or client.document or ''
		if document:
			pdf.cell(0, 5, _latin(f'Documento: {document}'), ln=True)
		client_address_parts = [
			client.address,
			client.number,
			client.district,
		]
		client_address = ', '.join(part for part in client_address_parts if part)
		if client_address:
			pdf.cell(0, 5, _latin(client_address), ln=True)
		city_state = ' - '.join(part for part in [client.city, client.state] if part)
		if city_state or client.zip_code:
			pdf.cell(0, 5, _latin(' - '.join(part for part in [city_state, client.zip_code] if part)), ln=True)
		if client.phone or client.email:
			pdf.cell(0, 5, _latin(' / '.join(part for part in [client.phone, client.email] if part)), ln=True)
	else:
		pdf.cell(0, 5, 'Não informado', ln=True)

	pdf.ln(6)

	columns = [
		('code', 'Código', 16, 'L'),
		('description', 'Descrição', 66, 'L'),
		('unit', 'Und.', 12, 'L'),
		('quantity', 'Qtd.', 16, 'R'),
		('delivery', 'Entrega (dias)', 22, 'C'),
		('unit_price', 'Valor Unit.', 22, 'R'),
		('discount', 'Desconto', 14, 'R'),
		('total', 'Subtotal', 18, 'R'),
	]

	table_width = sum(column[2] for column in columns)

	pdf.set_font('Helvetica', 'B', 8)
	pdf.set_fill_color(240, 240, 240)
	for _, header, width, align in columns:
		pdf.cell(width, 6, _latin(header), border=1, align=align, fill=True)
	pdf.ln(6)

	items = list(quote.items.filter(product__isnull=False).order_by('sort_order', 'pk'))
	pdf.set_font('Helvetica', '', 7)

	gross_total = Decimal('0.00')
	total_discount = Decimal('0.00')
	base_row_height = 5
	line_height = 3.8

	for item in items:
		product = item.product
		code = product.code if product and product.code else ''
		description = item.effective_description or (product.name if product else '')
		unit = product.unit if product and product.unit else ''
		quantity = item.quantity or Decimal('0')
		unit_price = item.unit_price or Decimal('0')
		discount_amount = item.discount or Decimal('0')
		line_gross = quantity * unit_price
		line_total = item.total_amount
		delivery_days = item.delivery_days

		gross_total += line_gross
		total_discount += discount_amount

		row_cells = {
			'code': _truncate(code, 12),
			'description': description,
			'unit': unit or '',
			'quantity': _format_decimal(quantity, 2, allow_blank=True),
			'delivery': str(int(delivery_days)) if delivery_days not in (None, '') else '',
			'unit_price': _format_currency(unit_price),
			'discount': _format_currency(discount_amount) if discount_amount else '',
			'total': _format_currency(line_total),
		}

		max_row_height = base_row_height
		for key, _, width, align in columns:
			if key != 'description':
				continue
			text = _latin(row_cells.get(key, ''))
			if not text:
				continue
			lines = pdf.multi_cell(width, line_height, text, border=0, align=align, split_only=True)
			height = max(len(lines), 1) * line_height
			max_row_height = max(max_row_height, height)

		start_x = pdf.get_x()
		start_y = pdf.get_y()

		for key, _, width, align in columns:
			text = row_cells.get(key, '')
			if align == 'R' and not text:
				text = ''
			if key == 'description':
				text = _latin(text)
				current_y = pdf.get_y()
				current_x = pdf.get_x()
				pdf.multi_cell(width, line_height, text, border=0, align=align)
				pdf.rect(current_x, current_y, width, max_row_height)
				pdf.set_xy(current_x + width, current_y)
			else:
				pdf.cell(width, max_row_height, _latin(text), border=1, align=align)

		pdf.set_xy(start_x, start_y + max_row_height)

	if not items:
		pdf.cell(table_width, base_row_height, 'Nenhum item informado.', border=1, align='C')
		pdf.ln(base_row_height)

	net_total = quote.total_amount or (gross_total - total_discount)
	acrescimo = Decimal('0.00')

	pdf.ln(6)

	pdf.set_font('Helvetica', 'B', 11)
	pdf.cell(0, 6, 'Resumo', ln=True)
	pdf.set_font('Helvetica', '', 10)
	pdf.cell(40, 6, 'Subtotal:', border=0)
	pdf.cell(0, 6, _latin(_format_currency(gross_total)), border=0, ln=1, align='R')
	pdf.cell(40, 6, 'Descontos:', border=0)
	pdf.cell(0, 6, _latin(_format_currency(total_discount)), border=0, ln=1, align='R')
	pdf.cell(40, 6, 'Acréscimo:', border=0)
	pdf.cell(0, 6, _latin(_format_currency(acrescimo)), border=0, ln=1, align='R')
	pdf.set_font('Helvetica', 'B', 10)
	pdf.cell(40, 7, 'Total:', border=0)
	pdf.cell(0, 7, _latin(_format_currency(net_total)), border=0, ln=1, align='R')

	pdf.ln(6)

	pdf.set_font('Helvetica', 'B', 11)
	pdf.cell(0, 6, 'Observações', ln=True)
	pdf.set_font('Helvetica', '', 10)
	if quote.notes:
		pdf.multi_cell(0, 5, _latin(quote.notes))
	else:
		pdf.cell(0, 5, _latin('—'), ln=True)

	response = HttpResponse(content_type='application/pdf')
	filename = f'orçamento-{quote.number or quote.pk}.pdf'.replace(' ', '_')
	response['Content-Disposition'] = f'inline; filename=\"{filename}\"'
	output = pdf.output(dest='S')
	if isinstance(output, str):
		response.write(output.encode('latin-1'))
	else:
		response.write(bytes(output))
	return response


@login_required
@transaction.atomic
def quote_create(request):
	perms, denial = _ensure_can_manage_sales(request, 'create', 'sales:quote_list')
	if denial:
		return denial
	if not getattr(request, 'company', None):
		messages.error(request, 'Selecione uma empresa antes de criar um orçamento.')
		return redirect('sales:quote_list')
	return _quote_form_view(request, perms=perms)


@login_required
@transaction.atomic
def quote_edit(request, pk):
	loja_codigo = getattr(request, 'loja_codigo', None)
	quote_qs = Quote.objects.all()
	if loja_codigo:
		quote_qs = quote_qs.filter(loja_codigo=loja_codigo)
	quote = get_object_or_404(quote_qs, pk=pk)
	perms = _get_sales_permissions(request.user)
	if not perms['manage'] or not perms.get('edit', False):
		messages.error(request, 'Você não tem permissão para editar este orçamento.')
		return redirect('sales:quote_detail', pk=quote.pk)
	if quote.company and quote.company not in getattr(request, 'available_companies', []):
		messages.error(request, 'Você não tem permissão para editar orçamentos desta empresa.')
		return redirect('sales:quote_list')
	return _quote_form_view(request, quote, perms=perms)


def _quote_form_view(request, instance=None, perms=None):
	quote = instance or Quote()
	active_company = getattr(request, 'company', None)
	loja_codigo = getattr(request, 'loja_codigo', None)
	perms = perms or _get_sales_permissions(request.user)
	if request.method != 'POST' and quote.pk:
		quote.items.filter(product__isnull=True, description='').delete()
	form = QuoteForm(instance=quote, user=request.user)
	formset = QuoteItemFormSet(instance=quote, prefix='items')
	formset.can_delete = perms.get('delete', False)
	form_valid = formset_valid = False

	if request.method == 'POST':
		form = QuoteForm(request.POST, instance=quote, user=request.user)
		formset = QuoteItemFormSet(request.POST, instance=quote, prefix='items')
		formset.can_delete = perms.get('delete', False)
		form_valid = form.is_valid()
		formset_valid = formset.is_valid()
		if formset_valid and not perms.get('delete', False) and formset.deleted_forms:
			formset._non_form_errors = formset.error_class(['Você não tem permissão para excluir itens do orçamento.'])
			formset_valid = False
		if form_valid and formset_valid:
			if quote.pk and quote.company and active_company and quote.company != active_company:
				messages.error(request, 'Este orçamento pertence a outra empresa.')
				return redirect('sales:quote_detail', pk=quote.pk)
			quote = form.save(commit=False)
			if not quote.pk and loja_codigo:
				quote.loja_codigo = loja_codigo
			if not quote.company:
				if active_company:
					quote.company = active_company
				else:
					messages.error(request, 'Selecione uma empresa antes de salvar o orçamento.')
					form_valid = False
			if form_valid and not quote.valid_until:
				config = SalesConfiguration.load()
				days = getattr(config, 'default_quote_validity_days', 0) or 0
				if days > 0:
					quote.valid_until = timezone.localdate() + timedelta(days=days)
			if form_valid:
				quote.save()
			else:
				formset_valid = False

	if form_valid and formset_valid:
		formset.instance = quote
		valid_item_forms = []
		orphan_instances = []
		for item_form in formset.forms:
			cleaned = getattr(item_form, 'cleaned_data', None) or {}
			if not cleaned:
				continue
			if cleaned.get('DELETE'):
				continue
			product = cleaned.get('product')
			if not product:
				if item_form.instance.pk:
					orphan_instances.append(item_form.instance)
				continue
			valid_item_forms.append(item_form)

		for index, item_form in enumerate(valid_item_forms):
			item = item_form.save(commit=False)
			if not item.description and item.product:
				item.description = item.product.name
			item.sort_order = index
			item.quote = quote
			if quote.loja_codigo:
				item.loja_codigo = quote.loja_codigo
			item.save()

		if perms.get('delete', False):
			for deleted_form in getattr(formset, 'deleted_forms', []):
				instance = deleted_form.instance
				if instance.pk:
					instance.delete()

		for orphan in orphan_instances:
			if orphan.pk:
				orphan.delete()

		# Ensure at least one item persisted
		if quote.items.filter(product__isnull=False).count() == 0:
			messages.error(request, 'Inclua pelo menos um item no orçamento.')
		else:
			messages.success(request, 'Orçamento salvo com sucesso.')
			return redirect('sales:quote_detail', pk=quote.pk)
	recent_drafts = Quote.objects.select_related('client').prefetch_related('items').filter(
		status=Quote.Status.DRAFT
	).order_by('-updated_at')
	if active_company:
		recent_drafts = recent_drafts.filter(company=active_company)
	if loja_codigo:
		recent_drafts = recent_drafts.filter(loja_codigo=loja_codigo)
	if quote.pk:
		recent_drafts = recent_drafts.exclude(pk=quote.pk)
	recent_drafts = list(recent_drafts[:6])
	existing_items = list(quote.items.filter(product__isnull=False).select_related('product')) if quote.pk else []
	item_metrics, summary = _build_quote_item_metrics(existing_items)
	for item_form in formset.forms:
		item_pk = getattr(item_form.instance, 'pk', None)
		item_form.metrics = item_metrics.get(item_pk)
	company_for_number = quote.company or active_company
	next_quote_number = quote.number or Quote.get_next_number(company_for_number)
	return render(request, 'sales/quote_form.html', {
		'form': form,
		'formset': formset,
		'is_edit': instance is not None,
		'quote': quote,
		'recent_drafts': recent_drafts,
		'quote_summary': summary,
		'next_quote_number': next_quote_number,
		'today': timezone.localdate(),
		'sales_permissions': perms,
		})


@login_required
def quote_product_lookup(request):
	term = (request.GET.get('q') or '').strip()
	limit = 12

	if not term:
		return JsonResponse({'results': []})

	qs = Product.objects.all()
	tokens = [t for t in term.replace('%', ' ').split() if t]
	for token in tokens:
		qs = qs.filter(
			Q(name__icontains=token)
			| Q(code__icontains=token)
			| Q(reference__icontains=token)
			| Q(gtin__icontains=token)
			| Q(description__icontains=token)
		)

	qs = qs.order_by('name')
	active_company = getattr(request, 'company', None)

	def _format_decimal(value, places=2):
		if value in (None, ''):
			return ''
		return f'{value:.{places}f}'

	results = []
	for product in qs.select_related(None).only(
		'id', 'code', 'name', 'price', 'stock', 'unit', 'cost_price', 'reference', 'gtin'
	)[:limit]:
		stock_value = product.stock_for_company(active_company) if active_company else product.stock
		label_parts = []
		if product.code:
			label_parts.append(product.code)
		label_parts.append(product.name)
		results.append({
			'id': product.pk,
			'code': product.code or '',
			'name': product.name or '',
			'label': ' - '.join(label_parts),
			'price': _format_decimal(product.price, 2),
			'stock': _format_decimal(stock_value, 2),
			'unit': product.unit or '',
			'cost_price': _format_decimal(product.cost_price, 4),
			'reference': product.reference or '',
			'gtin': product.gtin or '',
		})
	return JsonResponse({'results': results})


@login_required
@transaction.atomic
def quote_convert_to_order(request, pk):
	loja_codigo = getattr(request, 'loja_codigo', None)
	quote_qs = Quote.objects.select_related('client').prefetch_related('items__product')
	quote_qs = _filter_by_loja_codigo(quote_qs, loja_codigo)
	quote = get_object_or_404(quote_qs, pk=pk)
	if quote.company and quote.company not in getattr(request, 'available_companies', []):
		messages.error(request, 'Você não tem permissão para converter orçamentos desta empresa.')
		return redirect('sales:quote_detail', pk=quote.pk)
	perms = _get_sales_permissions(request.user)
	if not perms['manage'] or not perms.get('create', False):
		messages.error(request, 'Você não tem permissão para gerar pedidos a partir de orçamentos.')
		return redirect('sales:quote_detail', pk=quote.pk)
	if request.method == 'POST':
		if quote.items.filter(product__isnull=False).count() == 0:
			messages.error(request, 'Não é possível converter um orçamento sem itens.')
			return redirect('sales:quote_detail', pk=quote.pk)
		order = Order.objects.create(
			client=quote.client,
			quote=quote,
			status=Order.Status.DRAFT,
			company=quote.company,
			loja_codigo=quote.loja_codigo,
		)
		bulk = []
		for item in quote.items.filter(product__isnull=False):
			bulk.append(OrderItem(
				order=order,
				product=item.product,
				description=item.effective_description,
				quantity=item.quantity,
				unit_price=item.unit_price,
				discount=item.discount,
				sort_order=item.sort_order,
				loja_codigo=quote.loja_codigo,
			))
		OrderItem.objects.bulk_create(bulk)
		quote.status = Quote.Status.CONVERTED
		quote.save(update_fields=['status'])
		messages.success(request, f'Orçamento {quote.number} convertido em pedido {order.number}.')
		return redirect('sales:order_detail', pk=order.pk)
	return render(request, 'sales/quote_convert_confirm.html', {'quote': quote, 'sales_permissions': perms})


@login_required
def order_list(request):
	qs = Order.objects.select_related('client', 'quote').prefetch_related('items')
	qs, q, status = _apply_common_filters(qs, request)
	perms = _get_sales_permissions(request.user)
	context = {
		'orders': qs,
		'filters': {
			'q': q,
			'status': status,
		},
		'status_choices': Order.Status.choices,
 		'sales_permissions': perms,
	}
	return render(request, 'sales/order_list.html', context)


@login_required
def order_detail(request, pk):
	loja_codigo = getattr(request, 'loja_codigo', None)
	order_qs = Order.objects.select_related('client', 'quote').prefetch_related('items__product')
	order_qs = _filter_by_loja_codigo(order_qs, loja_codigo)
	order = get_object_or_404(order_qs, pk=pk)
	if order.company and order.company not in getattr(request, 'available_companies', []):
		messages.error(request, 'Você não tem permissão para acessar este pedido.')
		return redirect('sales:order_list')
	perms = _get_sales_permissions(request.user)
	return render(request, 'sales/order_detail.html', {'order': order, 'sales_permissions': perms})


@login_required
@transaction.atomic
def order_create(request):
	messages.error(request, 'Criação de pedidos desabilitada (somente leitura).')
	return redirect('sales:order_list')


@login_required
@transaction.atomic
def order_edit(request, pk):
	messages.error(request, 'Edição de pedidos desabilitada (somente leitura).')
	return redirect('sales:order_detail', pk=pk)


def _order_form_view(request, instance=None, perms=None):
	order = instance or Order()
	active_company = getattr(request, 'company', None)
	loja_codigo = getattr(request, 'loja_codigo', None)
	perms = perms or _get_sales_permissions(request.user)
	if request.method == 'POST':
		form = OrderForm(request.POST, instance=order)
		formset = OrderItemFormSet(request.POST, instance=order, prefix='items')
		if 'quote' in form.fields:
			if active_company:
				form.fields['quote'].queryset = Quote.objects.filter(company=active_company)
			else:
				form.fields['quote'].queryset = Quote.objects.none()
		formset.can_delete = perms.get('delete', False)
		form_valid = form.is_valid()
		formset_valid = formset.is_valid()
		if formset_valid and not perms.get('delete', False) and formset.deleted_forms:
			formset._non_form_errors = formset.error_class(['Você não tem permissão para excluir itens do pedido.'])
			formset_valid = False
		if form_valid and formset_valid:
			if order.pk and order.company and active_company and order.company != active_company:
				messages.error(request, 'Este pedido pertence a outra empresa.')
				return redirect('sales:order_detail', pk=order.pk)
			order = form.save(commit=False)
			if not order.pk and loja_codigo:
				order.loja_codigo = loja_codigo
			if not order.company:
				if active_company:
					order.company = active_company
				else:
					messages.error(request, 'Selecione uma empresa antes de salvar o pedido.')
					form_valid = False
			if form_valid:
				order.save()
			else:
				formset_valid = False
		if form_valid and formset_valid:
			formset.instance = order
			items = formset.save(commit=False)
			for index, item in enumerate(items):
				if not item.description and item.product:
					item.description = item.product.name
				item.sort_order = index
				if order.loja_codigo:
					item.loja_codigo = order.loja_codigo
				item.save()
			if perms.get('delete', False):
				for deleted in formset.deleted_objects:
					deleted.delete()
			if order.items.count() == 0:
				messages.error(request, 'Inclua pelo menos um item no pedido.')
			else:
				messages.success(request, 'Pedido salvo com sucesso.')
				return redirect('sales:order_detail', pk=order.pk)
	else:
		form = OrderForm(instance=order)
		if 'quote' in form.fields:
			if active_company:
				form.fields['quote'].queryset = Quote.objects.filter(company=active_company)
			else:
				form.fields['quote'].queryset = Quote.objects.none()
		formset = OrderItemFormSet(instance=order, prefix='items')
		formset.can_delete = perms.get('delete', False)
	return render(request, 'sales/order_form.html', {
		'form': form,
		'formset': formset,
		'is_edit': instance is not None,
		'sales_permissions': perms,
	})


@login_required
def seller_list(request, pk=None):
	instance = None
	if pk is not None:
		instance = get_object_or_404(Salesperson.objects.select_related('user'), pk=pk)

	if request.method == 'POST':
		form = SalespersonForm(request.POST, instance=instance)
		if form.is_valid():
			seller = form.save()
			if instance:
				messages.success(request, f'Vendedor "{seller}" atualizado com sucesso.')
			else:
				messages.success(request, f'Vendedor "{seller}" cadastrado.')
			return redirect('sales:seller_list')
	else:
		form = SalespersonForm(instance=instance)

	sellers = Salesperson.objects.select_related('user').order_by('user__first_name', 'user__last_name', 'user__username')
	return render(request, 'sales/seller_list.html', {
		'sellers': sellers,
		'form': form,
		'is_edit': instance is not None,
	})


@login_required
def seller_delete(request, pk):
	seller = get_object_or_404(Salesperson, pk=pk)
	if request.method == 'POST':
		name = str(seller)
		seller.delete()
		messages.success(request, f'Vendedor "{name}" removido.')
	return redirect('sales:seller_list')

# -------------------------------
# Pedidos recebidos pela API (FastAPI)
# -------------------------------
@login_required
def api_order_list(request):
	q = (request.GET.get('q') or '').strip()
	orders = Pedido.objects.select_related('cliente').order_by('-data_recebimento')
	loja_codigo = getattr(request, 'loja_codigo', None)
	orders = _filter_by_loja_codigo(orders, loja_codigo)
	if q:
		orders = orders.filter(
			Q(cliente__first_name__icontains=q) |
			Q(cliente__last_name__icontains=q) |
			Q(cliente__code__icontains=q) |
			Q(id__icontains=q)
		)
	return render(request, 'sales/api_order_list.html', {
		'orders': orders,
		'query': q,
	})


@login_required
def api_order_detail(request, pk):
	loja_codigo = getattr(request, 'loja_codigo', None)
	order_qs = Pedido.objects.select_related('cliente').prefetch_related(
		Prefetch('itens', queryset=ItemPedido.objects.select_related('produto'))
	)
	order_qs = _filter_by_loja_codigo(order_qs, loja_codigo)
	order = get_object_or_404(order_qs, pk=pk)
	items = []
	for item in order.itens.all():
		qty = item.quantidade or Decimal('0')
		unit = item.valor_unitario or Decimal('0')
		items.append({
			'instance': item,
			'subtotal': qty * unit,
		})
	return render(request, 'sales/api_order_detail.html', {
		'order': order,
		'items': items,
	})

# Create your views here.
