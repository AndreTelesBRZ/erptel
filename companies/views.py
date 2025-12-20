from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage
from django.http import JsonResponse
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from core.models import SefazConfiguration

from .forms import CompanyForm
from .models import Company
from .services import (
	SefazAPIError,
	fetch_company_data_from_sefaz,
	prepare_company_nfe_query,
	has_configured_sefaz_certificate,
	serialize_nfe_document,
)


@login_required
def company_list(request):
	search = (request.GET.get('q') or '').strip()
	status = request.GET.get('status') or ''

	qs = Company.objects.all()
	if search:
		qs = qs.filter(
			Q(name__icontains=search) |
			Q(trade_name__icontains=search) |
			Q(code__icontains=search) |
			Q(tax_id__icontains=search) |
			Q(email__icontains=search)
		)
	if status == 'inactive':
		qs = qs.filter(is_active=False)
	elif status == 'active':
		qs = qs.filter(is_active=True)

	paginator = Paginator(qs, 25)
	page_number = request.GET.get('page') or 1
	try:
		page_obj = paginator.page(page_number)
	except EmptyPage:
		page_obj = paginator.page(paginator.num_pages)

	config = SefazConfiguration.load()
	sefaz_nfe_ready = has_configured_sefaz_certificate(config)

	context = {
		'companies': page_obj.object_list,
		'page_obj': page_obj,
		'is_paginated': paginator.num_pages > 1,
		'filters': {
			'q': search,
			'status': status,
		},
		'sefaz_nfe_ready': sefaz_nfe_ready,
	}
	return render(request, 'companies/company_list.html', context)


@login_required
def company_create(request):
	if request.method == 'POST':
		form = CompanyForm(request.POST)
		if form.is_valid():
			company = form.save()
			messages.success(request, f'Empresa "{company}" cadastrada com sucesso.')
			return redirect('companies:list')
	else:
		form = CompanyForm()
	return render(request, 'companies/company_form.html', {'form': form})


@login_required
def company_edit(request, pk):
	company = get_object_or_404(Company, pk=pk)
	if request.method == 'POST':
		form = CompanyForm(request.POST, instance=company)
		if form.is_valid():
			form.save()
			messages.success(request, f'Empresa "{company}" atualizada.')
			return redirect('companies:list')
	else:
		form = CompanyForm(instance=company)
	return render(request, 'companies/company_form.html', {'form': form, 'company': company})


@login_required
def company_delete(request, pk):
	company = get_object_or_404(Company, pk=pk)
	if request.method == 'POST':
		name = str(company)
		company.delete()
		messages.success(request, f'Empresa "{name}" removida.')
		return redirect('companies:list')
	return render(request, 'companies/company_confirm_delete.html', {'company': company})


@login_required
@require_GET
def company_sefaz_lookup(request):
	cnpj = (request.GET.get('cnpj') or '').strip()
	if not cnpj:
		return JsonResponse({'error': 'Informe o CNPJ.'}, status=400)
	try:
		data = fetch_company_data_from_sefaz(cnpj)
	except ValueError as exc:
		return JsonResponse({'error': str(exc)}, status=400)
	except SefazAPIError as exc:
		return JsonResponse({'error': str(exc)}, status=502)
	return JsonResponse({'data': data})


@login_required
def company_nfe_list(request, pk):
	company = get_object_or_404(Company, pk=pk)
	params, result, error, sefaz_ready = prepare_company_nfe_query(company, {
		'last_nsu': request.GET.get('last_nsu', ''),
		'nsu': request.GET.get('nsu', ''),
		'access_key': request.GET.get('access_key', ''),
	})

	context = {
		'company': company,
		'result': result,
		'error': error,
		'params': params,
		'sefaz_ready': sefaz_ready,
	}
	return render(request, 'companies/company_nfe.html', context)


@login_required
def company_nfe_json(request, pk):
	company = get_object_or_404(Company, pk=pk)
	params, result, error, sefaz_ready = prepare_company_nfe_query(company, {
		'last_nsu': request.GET.get('last_nsu', ''),
		'nsu': request.GET.get('nsu', ''),
		'access_key': request.GET.get('access_key', ''),
	})

	if not sefaz_ready:
		return JsonResponse({'error': error, 'params': params}, status=503)
	if error:
		return JsonResponse({'error': error, 'params': params}, status=400)
	if not result:
		return JsonResponse({
			'message': 'Nenhuma resposta foi retornada pela SEFAZ.',
			'params': params,
		})

	documents = [serialize_nfe_document(doc) for doc in result.documents]
	return JsonResponse({
		'company': {
			'id': company.pk,
			'name': company.name,
			'tax_id': company.tax_id,
		},
		'params': params,
		'status_code': result.status_code,
		'status_message': result.status_message,
		'last_nsu': result.last_nsu,
		'max_nsu': result.max_nsu,
		'documents': documents,
		'count': len(documents),
	})

# Create your views here.
