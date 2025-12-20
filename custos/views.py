from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, Paginator
from django.forms import modelformset_factory
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from products.models import Supplier, SupplierProductPrice

from .forms import (
	CostBatchAddItemsForm,
	CostBatchForm,
	CostBatchItemForm,
	CostParameterForm,
	SupplierCostForm,
)
from .models import CostBatch, CostBatchItem, CostParameter


@login_required
def parameter_list(request):
	q = (request.GET.get('q') or '').strip()
	show_only_active = request.GET.get('active', '').lower() in ('1', 'true', 'yes', 'on')

	qs = CostParameter.objects.all()
	if q:
		qs = qs.filter(
			Q(label__icontains=q) |
			Q(key__icontains=q) |
			Q(description__icontains=q)
		)
	if show_only_active:
		qs = qs.filter(is_active=True)

	sort = (request.GET.get('sort') or 'label').lower()
	dir_ = (request.GET.get('dir') or 'asc').lower()
	sort_fields = {
		'label': 'label',
		'key': 'key',
		'value': 'value',
		'updated': 'updated_at',
	}
	order_field = sort_fields.get(sort, 'label')
	order_prefix = '' if dir_ == 'asc' else '-'
	qs = qs.order_by(f'{order_prefix}{order_field}', 'label')

	try:
		page = int(request.GET.get('page') or 1)
	except Exception:
		page = 1
	try:
		per_page = max(1, min(200, int(request.GET.get('per_page') or 50)))
	except Exception:
		per_page = 50

	paginator = Paginator(qs, per_page)
	try:
		page_obj = paginator.page(page)
	except EmptyPage:
		page_obj = paginator.page(paginator.num_pages)

	context = {
		'parameters': page_obj.object_list,
		'filters': {
			'q': q,
			'active': show_only_active,
		},
		'page_obj': page_obj,
		'is_paginated': paginator.num_pages > 1,
		'per_page': per_page,
		'per_page_options': [20, 50, 100, 200],
		'sort': sort,
		'dir': dir_,
		'total': paginator.count,
	}
	return render(request, 'custos/parameter_list.html', context)


@staff_member_required
def parameter_create(request):
	if request.method == 'POST':
		form = CostParameterForm(request.POST)
		if form.is_valid():
			parameter = form.save(commit=False)
			parameter.updated_by = request.user
			parameter.save()
			messages.success(request, 'Parâmetro criado com sucesso.')
			return redirect(reverse('custos:parameter_list'))
	else:
		form = CostParameterForm()
	return render(request, 'custos/parameter_form.html', {'form': form, 'is_edit': False})


@staff_member_required
def parameter_edit(request, pk):
	parameter = get_object_or_404(CostParameter, pk=pk)
	if request.method == 'POST':
		form = CostParameterForm(request.POST, instance=parameter)
		if form.is_valid():
			param = form.save(commit=False)
			param.updated_by = request.user
			param.save()
			messages.success(request, 'Parâmetro atualizado com sucesso.')
			return redirect(reverse('custos:parameter_list'))
	else:
		form = CostParameterForm(instance=parameter)
	return render(request, 'custos/parameter_form.html', {'form': form, 'is_edit': True, 'parameter': parameter})


@staff_member_required
def batch_list(request):
	q = (request.GET.get('q') or '').strip()
	qs = CostBatch.objects.all()
	if q:
		qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
	context = {
		'batches': qs,
		'q': q,
	}
	return render(request, 'custos/batch_list.html', context)


@staff_member_required
def batch_create(request):
	if request.method == 'POST':
		form = CostBatchForm(request.POST)
		if form.is_valid():
			batch = form.save(commit=False)
			batch.created_by = request.user
			batch.save()
			messages.success(request, 'Lote criado com sucesso. Agora selecione os itens.')
			return redirect('custos:batch_detail', pk=batch.pk)
	else:
		form = CostBatchForm()
	return render(request, 'custos/batch_form.html', {'form': form})


BatchItemFormSet = modelformset_factory(
	CostBatchItem,
	form=CostBatchItemForm,
	extra=0,
	can_delete=True,
)


@staff_member_required
def batch_detail(request, pk):
	batch = get_object_or_404(CostBatch, pk=pk)
	items_qs = batch.items.select_related('supplier_item', 'supplier_item__supplier', 'supplier_item__product')
	formset = BatchItemFormSet(request.POST or None, queryset=items_qs, prefix='items')
	add_form = CostBatchAddItemsForm(request.POST or None, prefix='add')
	preview_mode = False
	if request.method == 'POST' and request.POST.get('action') == 'add_lookup_item':
		supplier_item_id = (request.POST.get('supplier_item_id') or '').strip()
		raw_multiple_ids = (request.POST.get('supplier_item_ids') or '').strip()
		id_list = []
		if raw_multiple_ids:
			id_list.extend([part.strip() for part in raw_multiple_ids.split(',') if part.strip()])
		if supplier_item_id:
			if supplier_item_id not in id_list:
				id_list.append(supplier_item_id)
		if not id_list:
			messages.error(request, 'Selecione um item para adicionar.')
		else:
			added = 0
			not_found = []
			for supplier_item_id in id_list:
				supplier_item = SupplierProductPrice.objects.filter(pk=supplier_item_id).first()
				if not supplier_item:
					not_found.append(supplier_item_id)
					continue
				item, created = CostBatchItem.objects.get_or_create(
					batch=batch,
					code=supplier_item.code,
					defaults={
						'supplier_item': supplier_item,
						'description': supplier_item.description or '',
						'unit': supplier_item.unit or '',
						'quantity': supplier_item.quantity or Decimal('1'),
						'pack_quantity': supplier_item.pack_quantity,
						'unit_price': supplier_item.unit_price or Decimal('0'),
						'ipi_percent': supplier_item.ipi_percent if supplier_item.ipi_percent is not None else batch.default_ipi_percent,
						'freight_percent': supplier_item.freight_percent if supplier_item.freight_percent is not None else batch.default_freight_percent,
					},
				)
				if not created:
					item.supplier_item = supplier_item
					if supplier_item.unit_price not in (None, ''):
						item.unit_price = supplier_item.unit_price
					if supplier_item.ipi_percent not in (None, ''):
						item.ipi_percent = supplier_item.ipi_percent
					if supplier_item.freight_percent not in (None, ''):
						item.freight_percent = supplier_item.freight_percent
					item.description = supplier_item.description or item.description
					item.unit = supplier_item.unit or item.unit
					item.pack_quantity = supplier_item.pack_quantity
				item.save()
				added += 1
			if added == 1 and len(id_list) == 1:
				messages.success(request, 'Item adicionado ao lote.')
			elif added:
				messages.success(request, f'{added} itens adicionados ao lote.')
			if not_found:
				messages.warning(request, f'Itens não encontrados: {", ".join(not_found)}.')
		return redirect('custos:batch_detail', pk=batch.pk)

	if request.method == 'POST' and 'add_items' in request.POST:
		if add_form.is_valid():
			codes = add_form.cleaned_data['codes']
			added = 0
			not_found = []
			for code in codes:
				supplier_item = SupplierProductPrice.objects.filter(code=code).order_by('-valid_until', '-id').first()
				if not supplier_item:
					not_found.append(code)
					continue
				item, created = CostBatchItem.objects.get_or_create(
					batch=batch,
					code=supplier_item.code,
					defaults={
						'supplier_item': supplier_item,
						'description': supplier_item.description or '',
						'unit': supplier_item.unit or '',
						'quantity': supplier_item.quantity or Decimal('1'),
						'pack_quantity': supplier_item.pack_quantity,
						'unit_price': supplier_item.unit_price or Decimal('0'),
						'ipi_percent': supplier_item.ipi_percent if supplier_item.ipi_percent is not None else batch.default_ipi_percent,
						'freight_percent': supplier_item.freight_percent if supplier_item.freight_percent is not None else batch.default_freight_percent,
					},
				)
				if not created:
					item.supplier_item = supplier_item
					if supplier_item.unit_price not in (None, ''):
						item.unit_price = supplier_item.unit_price
					if supplier_item.ipi_percent not in (None, ''):
						item.ipi_percent = supplier_item.ipi_percent
					if supplier_item.freight_percent not in (None, ''):
						item.freight_percent = supplier_item.freight_percent
					item.description = supplier_item.description or item.description
					item.unit = supplier_item.unit or item.unit
					item.pack_quantity = supplier_item.pack_quantity
				item.save()
				added += 1
			if added:
				messages.success(request, f'{added} itens adicionados ao lote.')
			if not_found:
				messages.warning(request, f'Itens não encontrados: {", ".join(not_found)}.')
			return redirect('custos:batch_detail', pk=batch.pk)

	if request.method == 'POST' and 'preview_items' in request.POST:
		if formset.is_valid():
			preview_mode = True
			for form in formset:
				if form.cleaned_data.get('DELETE'):
					continue
				item = form.save(commit=False)
				item.batch = batch
				item.recompute_totals()
			messages.info(request, 'Cálculos atualizados. Revise e confirme para salvar no cadastro.')
		else:
			messages.error(request, 'Corrija os erros para visualizar os cálculos.')

	if request.method == 'POST' and 'save_items' in request.POST:
		if formset.is_valid():
			updated = 0
			deleted = 0
			supplier_updates = 0
			product_updates = 0
			active_company = getattr(request, 'company', None)
			now = timezone.now()
			for form in formset:
				if form.cleaned_data.get('DELETE'):
					if form.instance.pk:
						form.instance.delete()
						deleted += 1
					continue
				if not form.has_changed():
					continue
				item = form.save(commit=False)
				item.batch = batch
				item.save()
				updated += 1
				supplier_item = item.supplier_item
				if supplier_item:
					supplier_item.unit_price = item.unit_price
					supplier_item.ipi_percent = item.ipi_percent
					supplier_item.freight_percent = item.freight_percent
					supplier_item.replacement_cost = item.replacement_cost
					supplier_item.st_percent = batch.st_percent
					supplier_item.save(update_fields=[
						'unit_price',
						'ipi_percent',
						'freight_percent',
						'replacement_cost',
						'st_percent',
						'updated_at',
					])
					supplier_updates += 1
					product = supplier_item.product
					if product:
						product.cost_price = item.replacement_cost
						product.cost_price_updated_at = now
						update_fields = ['cost_price', 'cost_price_updated_at']
						if active_company:
							product.cost_price_company = active_company
							update_fields.append('cost_price_company')
						product.save(update_fields=update_fields)
						product_updates += 1
			if updated or deleted:
				parts = []
				if updated:
					details = []
					if supplier_updates:
						details.append(f'{supplier_updates} fornecedores sincronizados')
					if product_updates:
						target = f'{product_updates} produtos atualizados'
						if active_company:
							target += f' ({active_company.trade_name or active_company.name})'
						details.append(target)
					if details:
						parts.append(f'{updated} itens atualizados · ' + ' · '.join(details))
					else:
						parts.append(f'{updated} itens atualizados')
				if deleted:
					parts.append(f'{deleted} itens removidos')
				messages.success(request, f'{" e ".join(parts)} com sucesso.')
			else:
				messages.info(request, 'Nenhum item foi alterado.')
			return redirect('custos:batch_detail', pk=batch.pk)
		else:
			messages.error(request, 'Corrija os erros para salvar as alterações.')

	rows = []
	for form in formset.forms:
		item = form.instance
		rows.append({
			'form': form,
			'item': item,
		})

	summary = items_qs.aggregate(
		total_unit=Sum('unit_price'),
		total_replacement=Sum('replacement_cost'),
	)
	if preview_mode and formset.is_valid():
		total_unit = Decimal('0')
		total_replacement = Decimal('0')
		for row in rows:
			if row['form'].cleaned_data.get('DELETE'):
				continue
			total_unit += row['form'].cleaned_data.get('unit_price') or Decimal('0')
			total_replacement += row['item'].replacement_cost or Decimal('0')
		summary = {
			'total_unit': total_unit,
			'total_replacement': total_replacement,
		}

	context = {
		'batch': batch,
		'formset': formset,
		'add_form': add_form,
		'rows': rows,
		'total_items': items_qs.count(),
		'summary': summary,
		'preview_mode': preview_mode,
	}
	return render(request, 'custos/batch_detail.html', context)


@staff_member_required
def batch_select_items(request, pk):
	batch = get_object_or_404(CostBatch, pk=pk)
	qs = SupplierProductPrice.objects.select_related('supplier', 'product')
	q = (request.GET.get('q') or '').strip()
	supplier_id = request.GET.get('supplier')
	per_page_raw = request.GET.get('per_page')
	try:
		per_page = max(1, min(200, int(per_page_raw or 50)))
	except Exception:
		per_page = 50
	if q:
		parts = [p for p in q.replace('%', ' ').split() if p]
		for part in parts:
			qs = qs.filter(
				Q(code__icontains=part)
				| Q(description__icontains=part)
				| Q(product__name__icontains=part)
			)
	if supplier_id:
		try:
			supplier_id_int = int(supplier_id)
			qs = qs.filter(supplier_id=supplier_id_int)
		except Exception:
			supplier_id = ''
	qs = qs.order_by('code')
	paginator = Paginator(qs, per_page)
	page_number = request.GET.get('page') or 1
	try:
		page_obj = paginator.page(page_number)
	except EmptyPage:
		page_obj = paginator.page(paginator.num_pages)
	items = page_obj.object_list

	if request.method == 'POST':
		selected_ids = request.POST.getlist('item_ids')
		if not selected_ids:
			messages.warning(request, 'Selecione ao menos um item para adicionar ao lote.')
		else:
			items_to_add = SupplierProductPrice.objects.filter(id__in=selected_ids)
			added = 0
			for supplier_item in items_to_add:
				item, created = CostBatchItem.objects.get_or_create(
					batch=batch,
					code=supplier_item.code,
					defaults={
						'supplier_item': supplier_item,
						'description': supplier_item.description or '',
						'unit': supplier_item.unit or '',
						'quantity': supplier_item.quantity or Decimal('1'),
						'pack_quantity': supplier_item.pack_quantity,
						'unit_price': supplier_item.unit_price or Decimal('0'),
						'ipi_percent': supplier_item.ipi_percent if supplier_item.ipi_percent is not None else batch.default_ipi_percent,
						'freight_percent': supplier_item.freight_percent if supplier_item.freight_percent is not None else batch.default_freight_percent,
					},
				)
				if not created:
					item.supplier_item = supplier_item
					if supplier_item.unit_price not in (None, ''):
						item.unit_price = supplier_item.unit_price
					if supplier_item.ipi_percent not in (None, ''):
						item.ipi_percent = supplier_item.ipi_percent
					if supplier_item.freight_percent not in (None, ''):
						item.freight_percent = supplier_item.freight_percent
					item.description = supplier_item.description or item.description
					item.unit = supplier_item.unit or item.unit
					item.pack_quantity = supplier_item.pack_quantity
				item.save()
				added += 1
			if added:
				messages.success(request, f'{added} itens adicionados ao lote.')
			else:
				messages.info(request, 'Nenhum item novo foi adicionado.')
		return redirect('custos:batch_detail', pk=batch.pk)

	suppliers = Supplier.objects.order_by('name')
	context = {
		'batch': batch,
		'items': items,
		'page_obj': page_obj,
		'is_paginated': paginator.num_pages > 1,
		'per_page': per_page,
		'per_page_options': [20, 50, 100, 200],
		'q': q,
		'supplier_id': supplier_id,
		'suppliers': suppliers,
		'total': paginator.count,
	}
	return render(request, 'custos/batch_select_items.html', context)


ST_MULTIPLIER = Decimal('1.35')
ST_PERCENT = Decimal('24')


def _calc_components(base_price: Decimal, ipi_percent: Decimal, freight_percent: Decimal):
	base = base_price or Decimal('0')
	ipi_percent = ipi_percent or Decimal('0')
	freight_percent = freight_percent or Decimal('0')
	def _component(value):
		return (base * value / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if value else Decimal('0.00')

	ipi_value = _component(ipi_percent)
	freight_value = _component(freight_percent)

	st_value = ((base + ipi_value + freight_value) * ST_MULTIPLIER * (ST_PERCENT / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
	replacement_cost = (base + ipi_value + freight_value + st_value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
	return {
		'ipi_value': ipi_value,
		'freight_value': freight_value,
		'st_value': st_value,
		'replacement_cost': replacement_cost,
		'ipi_percent': ipi_percent,
		'freight_percent': freight_percent,
		'st_percent': ST_PERCENT,
	}


def _extract_decimal(form, field_name, default=Decimal('0')):
	if form.is_bound:
		raw = form.data.get(form.add_prefix(field_name))
		if raw not in (None, ''):
			try:
				return Decimal(str(raw).replace(',', '.'))
			except Exception:
				pass
	initial = form.initial.get(field_name) if isinstance(form.initial, dict) else None
	if initial not in (None, ''):
		try:
			return Decimal(initial)
		except Exception:
			pass
	instance_value = getattr(form.instance, field_name, None)
	if instance_value not in (None, ''):
		return Decimal(instance_value)
	return default


def _extract_unit_price(form):
	if form.is_bound:
		raw = form.data.get(form.add_prefix('unit_price'))
		if raw not in (None, ''):
			try:
				return Decimal(str(raw).replace(',', '.'))
			except Exception:
				pass
	initial = form.initial.get('unit_price') if isinstance(form.initial, dict) else None
	if initial not in (None, ''):
		try:
			return Decimal(initial)
		except Exception:
			pass
	if form.instance.unit_price not in (None, ''):
		return form.instance.unit_price
	return Decimal('0')


@staff_member_required
def purchase_costs(request):
	codes_raw = (request.GET.get('codes') or '').strip()
	search = (request.GET.get('q') or '').strip()
	supplier_id = request.GET.get('supplier')
	update_products = bool(request.POST.get('update_products'))

	qs = SupplierProductPrice.objects.select_related('supplier', 'product').all()
	codes = []
	if codes_raw:
		codes = [c.strip() for c in codes_raw.replace(';', ',').split(',') if c.strip()]
		if codes:
			qs = qs.filter(code__in=codes)
	if search:
		qs = qs.filter(
			Q(code__icontains=search) |
			Q(description__icontains=search)
		)
	if supplier_id:

		try:
			qs = qs.filter(supplier_id=int(supplier_id))
		except Exception:
			pass

	qs = qs.order_by('code')

	formset_class = modelformset_factory(
		SupplierProductPrice,
		form=SupplierCostForm,
		extra=0,
	)

	if request.method == 'POST':
		formset = formset_class(request.POST, queryset=qs)
		if formset.is_valid():
			updated = 0
			has_errors = False
			for form in formset:
				if not form.has_changed():
					continue
				item = form.save(commit=False)
				unit_price = form.cleaned_data.get('unit_price') or Decimal('0')
				ipi_percent = form.cleaned_data.get('ipi_percent') or Decimal('0')
				freight_percent = form.cleaned_data.get('freight_percent') or Decimal('0')
				if unit_price < 0:
					form.add_error('unit_price', 'Informe um valor não negativo.')
					has_errors = True
					continue
				if ipi_percent < 0:
					form.add_error('ipi_percent', 'Informe um percentual não negativo.')
					has_errors = True
					continue
				if freight_percent < 0:
					form.add_error('freight_percent', 'Informe um percentual não negativo.')
					has_errors = True
					continue
				item.unit_price = unit_price
				item.ipi_percent = ipi_percent
				item.freight_percent = freight_percent
				item.st_percent = ST_PERCENT  # guardar referência do percentual utilizado
				components = _calc_components(unit_price, ipi_percent, freight_percent)
				item.replacement_cost = components['replacement_cost']
				item.save(update_fields=['unit_price', 'ipi_percent', 'freight_percent', 'st_percent', 'replacement_cost'])
				if update_products and item.product:
					product = item.product
					update_fields = ['cost_price', 'cost_price_updated_at']
					product.cost_price = item.replacement_cost
					product.cost_price_updated_at = timezone.now()
					active_company = getattr(request, 'company', None)
					if active_company:
						product.cost_price_company = active_company
						update_fields.append('cost_price_company')
					product.save(update_fields=update_fields)
				updated += 1
			if has_errors:
				messages.error(request, 'Não foi possível atualizar alguns itens. Corrija os campos destacados.')
			else:
				if updated:
					messages.success(request, f'{updated} itens atualizados com sucesso.')
				else:
					messages.info(request, 'Nenhum item foi alterado.')
				return redirect(f"{reverse('custos:purchase_costs')}?{request.GET.urlencode()}")
	else:
		formset = formset_class(queryset=qs)

	rows = []
	for form in formset.forms:
		item = form.instance
		current_price = _extract_unit_price(form)
		ipi_percent = _extract_decimal(form, 'ipi_percent', default=item.ipi_percent or Decimal('0'))
		freight_percent = _extract_decimal(form, 'freight_percent', default=item.freight_percent or Decimal('0'))
		components = _calc_components(current_price, ipi_percent, freight_percent)
		rows.append({
			'form': form,
			'item': item,
			'components': components,
			'unit_price': current_price,
			'ipi_percent': ipi_percent,
			'freight_percent': freight_percent,
		})

	context = {
		'formset': formset,
		'rows': rows,
		'codes_raw': codes_raw,
		'search': search,
		'supplier_id': supplier_id,
		'update_products_flag': update_products,
		'total': qs.count(),
	}
	return render(request, 'custos/purchase_costs.html', context)
