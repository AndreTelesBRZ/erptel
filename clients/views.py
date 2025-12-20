from django.shortcuts import render, get_object_or_404, redirect
import re
from django.urls import reverse
from django.db import connection
from django.db.models.functions import Greatest
from django.contrib import messages
from django.http import HttpResponse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.http import JsonResponse
from django.views.decorators.http import require_GET
try:
	from django.contrib.postgres.search import TrigramSimilarity
except Exception:
	TrigramSimilarity = None
from fpdf import FPDF
from .models import Client, ClienteSync
from .forms import ClientForm
from django.contrib.auth.decorators import login_required
from companies.services import SefazAPIError, fetch_company_data_from_sefaz
from core.models import SefazConfiguration
from core.utils.documents import normalize_cnpj
from django.core.paginator import Paginator
from django.db.models import Q


def index(request):
	qs = Client.objects.all()
	q = (request.GET.get('q') or '').strip()
	has_phone = request.GET.get('has_phone')
	# sorting + pagination
	raw_sort = request.GET.get('sort')
	sort = (raw_sort or '').lower() or 'created'
	dir_ = (request.GET.get('dir') or '').lower() or 'desc'
	try:
		page = int(request.GET.get('page') or 1)
	except Exception:
		page = 1
	# Preferência de itens por página: GET > cookie global > cookie legado > padrão
	_per_page_src = (
		request.GET.get('per_page')
		or request.COOKIES.get('pref_per_page')
		or request.COOKIES.get('pref_per_page_clients')
	)
	try:
		per_page = max(1, min(200, int(_per_page_src or 50)))
	except Exception:
		per_page = 50

	# Visualização compacta: GET > cookie
	if 'dense' in request.GET:
		dense_param = (request.GET.get('dense') or '').strip().lower()
		dense = dense_param in ('1', 'true', 'yes', 'y', 'on')
	else:
		# Prefer global cookie; fallback to clients-specific for backward compatibility
		dense_cookie_global = (request.COOKIES.get('pref_dense') or '').strip().lower()
		dense_cookie_clients = (request.COOKIES.get('pref_dense_clients') or '').strip().lower()
		dense = (
			dense_cookie_global in ('1', 'true', 'yes', 'y', 'on') or
			dense_cookie_clients in ('1', 'true', 'yes', 'y', 'on')
		)

	if q:
		from django.db.models import Q
		if '%' in q and connection.vendor == 'postgresql':
			parts = [re.escape(p) for p in q.split('%') if p]
			pattern = '.*' + '.*'.join(parts) + '.*'
			query = (
				Q(first_name__iregex=pattern) |
				Q(last_name__iregex=pattern) |
				Q(email__iregex=pattern) |
				Q(phone__iregex=pattern) |
				Q(document__iregex=pattern) |
				Q(code__iregex=pattern)
			)
			qs = qs.filter(query)
		else:
			parts = [p for p in re.split(r"[%\s]+", q) if p]
			if parts:
				for p in parts:
					digit_fragment = ''.join(ch for ch in p if ch.isdigit())
					fragment_query = (
						Q(first_name__icontains=p) |
						Q(last_name__icontains=p) |
						Q(email__icontains=p) |
						Q(phone__icontains=p)
					)
					if digit_fragment:
						fragment_query |= Q(document__icontains=digit_fragment) | Q(code__icontains=digit_fragment)
					else:
						fragment_query |= Q(document__icontains=p) | Q(code__icontains=p)
					qs = qs.filter(fragment_query)
			else:
				digit_fragment = ''.join(ch for ch in q if ch.isdigit())
				base_query = (
					Q(first_name__icontains=q) |
					Q(last_name__icontains=q) |
					Q(email__icontains=q) |
					Q(phone__icontains=q)
				)
				if digit_fragment:
					base_query |= Q(document__icontains=digit_fragment) | Q(code__icontains=digit_fragment)
				else:
					base_query |= Q(document__icontains=q) | Q(code__icontains=q)
				qs = qs.filter(base_query)
	if has_phone:
		qs = qs.exclude(phone__isnull=True).exclude(phone='')

	# Ordenação
	relevance_supported = bool(q and connection.vendor == 'postgresql' and TrigramSimilarity)
	if relevance_supported:
		try:
			qs = qs.annotate(
				score=TrigramSimilarity('first_name', q)
				+ TrigramSimilarity('last_name', q)
				+ TrigramSimilarity('email', q)
				+ TrigramSimilarity('phone', q)
			)
		except Exception:
			relevance_supported = False

	sort_fields = {
		'name': 'first_name',
		'email': 'email',
		'document': 'document',
		'created': 'created_at',
		'relevance': 'score',
	}
	# Default para relevância quando disponível e sort não informado
	if (not raw_sort) and relevance_supported:
		sort = 'relevance'
	order_field = sort_fields.get(sort, 'created_at')
	if order_field == 'score' and not relevance_supported:
		order_field = 'created_at'
	prefix = '' if dir_ == 'asc' else '-'
	if order_field == 'created_at':
		qs = qs.order_by(prefix + order_field)
	else:
		qs = qs.order_by(prefix + order_field, '-created_at')

	# Paginação
	from django.core.paginator import Paginator, EmptyPage
	paginator = Paginator(qs, per_page)
	try:
		page_obj = paginator.page(page)
	except EmptyPage:
		page_obj = paginator.page(paginator.num_pages)

	clients = page_obj.object_list
	context = {
		'clients': clients,
		'filters': {
			'q': q,
			'has_phone': bool(has_phone),
		},
		'total': paginator.count,
		'page_obj': page_obj,
		'is_paginated': paginator.num_pages > 1,
		'per_page': per_page,
		'per_page_options': [20, 50, 100, 200],
		'dense': dense,
		'sort': sort,
		'dir': dir_,
	}
	response = render(request, 'clients/index.html', context)
	# Persistir preferências quando definidas via GET
	if 'per_page' in request.GET:
		# Grava cookie global e o legado (compatibilidade)
		response.set_cookie('pref_per_page', str(per_page), max_age=60*60*24*365)
		response.set_cookie('pref_per_page_clients', str(per_page), max_age=60*60*24*365)
	if 'dense' in request.GET:
		response.set_cookie('pref_dense_clients', '1' if dense else '0', max_age=60*60*24*365)
		# Keep a global cookie in sync so Dashboard and outras listas use the same pref
		response.set_cookie('pref_dense', '1' if dense else '0', max_age=60*60*24*365)
	return response


def detail(request, pk):
	client = get_object_or_404(Client, pk=pk)
	return render(request, 'clients/detail.html', {'client': client})


@login_required
def create(request):
	messages.error(request, 'Criação de clientes desabilitada (somente leitura).')
	return redirect('clients:index')


@login_required
def update(request, pk):
	get_object_or_404(Client, pk=pk)  # ensure exists
	messages.error(request, 'Edição de clientes desabilitada (somente leitura).')
	return redirect('clients:detail', pk=pk)


@login_required
def delete(request, pk):
	get_object_or_404(Client, pk=pk)  # ensure exists
	messages.error(request, 'Exclusão de clientes desabilitada (somente leitura).')
	return redirect('clients:detail', pk=pk)


@login_required
@require_GET
def client_sefaz_lookup(request):
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
		'person_type': Client.PersonType.LEGAL,
		'document': data.get('tax_id') or cnpj,
		'code': cnpj_digits,
		'first_name': data.get('name') or '',
		'last_name': data.get('trade_name') or '',
		'email': data.get('email') or '',
		'phone': data.get('phone') or '',
		'state_registration': data.get('state_registration') or '',
		'address': data.get('address') or '',
		'number': data.get('number') or '',
		'complement': data.get('complement') or '',
		'district': data.get('district') or '',
		'city': data.get('city') or '',
		'state': data.get('state') or '',
		'zip_code': data.get('zip_code') or '',
	}
	return JsonResponse({'data': response_data})


@login_required
def sync_list(request):
	q = (request.GET.get('q') or '').strip()
	sort = (request.GET.get('sort') or 'updated').lower()
	dir_ = (request.GET.get('dir') or 'desc').lower()
	page = request.GET.get('page') or 1
	try:
		per_page = max(10, min(200, int(request.GET.get('per_page') or 50)))
	except Exception:
		per_page = 50

	qs = ClienteSync.objects.all()
	if q:
		parts = [p.strip() for p in re.split(r"[%\s]+", q) if p.strip()]
		if parts:
			for p in parts:
				digit_fragment = ''.join(ch for ch in p if ch.isdigit())
				query = (
					Q(cliente_codigo__icontains=p) |
					Q(cliente_razao_social__icontains=p) |
					Q(cliente_nome_fantasia__icontains=p) |
					Q(cliente_email__icontains=p) |
					Q(vendedor_nome__icontains=p)
				)
				if digit_fragment:
					query |= Q(cliente_cnpj_cpf__icontains=digit_fragment) | Q(cliente_telefone1__icontains=digit_fragment) | Q(cliente_telefone2__icontains=digit_fragment)
				qs = qs.filter(query)
		else:
			qs = qs.filter(
				Q(cliente_codigo__icontains=q) |
				Q(cliente_razao_social__icontains=q) |
				Q(cliente_nome_fantasia__icontains=q) |
				Q(cliente_email__icontains=q) |
				Q(vendedor_nome__icontains=q) |
				Q(cliente_cnpj_cpf__icontains=''.join(ch for ch in q if ch.isdigit()))
			)

	sort_fields = {
		'codigo': 'cliente_codigo',
		'nome': 'cliente_razao_social',
		'fantasia': 'cliente_nome_fantasia',
		'documento': 'cliente_cnpj_cpf',
		'email': 'cliente_email',
		'vendedor': 'vendedor_nome',
		'ultima_venda': 'ultima_venda_data',
		'valor_venda': 'ultima_venda_valor',
		'updated': 'updated_at',
	}
	order_field = sort_fields.get(sort, 'updated_at')
	order_prefix = '' if dir_ == 'asc' else '-'
	qs = qs.order_by(f'{order_prefix}{order_field}', 'cliente_codigo')

	paginator = Paginator(qs, per_page)
	page_obj = paginator.get_page(page)

	last_sync_at = None
	try:
		with connection.cursor() as cursor:
			cursor.execute("SELECT max(updated_at) FROM erp_clientes_vendedores")
			row = cursor.fetchone()
			if row and row[0]:
				last_sync_at = timezone.localtime(row[0])
	except Exception:
		last_sync_at = None

	context = {
		'items': page_obj.object_list,
		'filters': {'q': q},
		'page_obj': page_obj,
		'is_paginated': paginator.num_pages > 1,
		'per_page': per_page,
		'per_page_options': [25, 50, 100, 200],
		'sort': sort,
		'dir': dir_,
		'total': paginator.count,
		'last_sync_at': last_sync_at,
	}
	response = render(request, 'clients/sync_list.html', context)
	if 'per_page' in request.GET:
		response.set_cookie('pref_per_page', str(per_page), max_age=60*60*24*365)
	return response


def report(request):
	total = Client.objects.count()
	return render(request, 'clients/report.html', {'total': total})


@login_required
def export_csv(request):
	import csv

	response = HttpResponse(content_type='text/csv; charset=utf-8')
	response['Content-Disposition'] = 'attachment; filename="clients.csv"'
	sep_param = (request.GET.get('sep') or ';').lower()
	if sep_param in (',', 'comma', 'coma'):
		delimiter = ','
	elif sep_param in ('\t', 'tab', 't'):
		delimiter = '\t'
	else:
		delimiter = ';'

	response.write('\ufeff')
	response.write(f"sep={delimiter}\n")
	writer = csv.writer(response, delimiter=delimiter)
	writer.writerow(['id', 'first_name', 'last_name', 'email', 'phone', 'created_at'])
	for c in Client.objects.all().order_by('id'):
		writer.writerow([c.id, c.first_name, c.last_name, c.email, c.phone, c.created_at])
	return response


@login_required
def export_pdf(request):
	def _truncate(text, limit):
		text = text or ''
		return text if len(text) <= limit else text[: limit - 1] + '…'

	return_url = request.POST.get('return_url')
	if return_url and not url_has_allowed_host_and_scheme(return_url, allowed_hosts={request.get_host()}):
		return_url = None
	return_url = return_url or reverse('clients:index')
	if request.method != 'POST':
		messages.error(request, 'Selecione os clientes desejados antes de gerar o PDF.')
		return redirect(return_url)

	selected_ids = request.POST.getlist('client_ids')
	if not selected_ids:
		messages.error(request, 'Selecione ao menos um cliente para gerar o PDF.')
		return redirect(return_url)

	clients_qs = Client.objects.filter(pk__in=selected_ids).order_by('first_name', 'last_name', 'id')
	clients = list(clients_qs)
	if not clients:
		messages.warning(request, 'Os clientes selecionados não estão mais disponíveis.')
		return redirect(return_url)

	pdf = FPDF()
	pdf.set_auto_page_break(auto=True, margin=15)
	pdf.add_page()
	pdf.set_font('Helvetica', 'B', 16)
	pdf.cell(0, 10, 'Relatório de Clientes', ln=True)

	pdf.set_font('Helvetica', '', 12)
	now = timezone.localtime()
	pdf.cell(0, 8, f'Gerado em: {now.strftime("%d/%m/%Y %H:%M")}', ln=True)
	pdf.cell(0, 8, f'Total selecionado: {len(clients)}', ln=True)
	pdf.ln(4)

	pdf.set_font('Helvetica', 'B', 11)
	pdf.set_fill_color(240, 240, 240)
	pdf.cell(15, 8, 'ID', border=1, fill=True)
	pdf.cell(60, 8, 'Nome', border=1, fill=True)
	pdf.cell(60, 8, 'Email', border=1, fill=True)
	pdf.cell(35, 8, 'Telefone', border=1, fill=True)
	pdf.cell(0, 8, 'Criado em', border=1, fill=True, ln=True)

	pdf.set_font('Helvetica', '', 10)
	for client in clients:
		name = f'{client.first_name} {client.last_name}'.strip()
		created_at = timezone.localtime(client.created_at).strftime('%d/%m/%Y %H:%M')

		pdf.cell(15, 8, str(client.pk), border=1)
		pdf.cell(60, 8, _truncate(name, 35), border=1)
		pdf.cell(60, 8, _truncate(client.email or '-', 40), border=1)
		pdf.cell(35, 8, _truncate(client.phone or '-', 20), border=1)
		pdf.cell(0, 8, created_at, border=1, ln=True)

	response = HttpResponse(content_type='application/pdf')
	response['Content-Disposition'] = 'attachment; filename="clientes.pdf"'
	pdf_output = pdf.output(dest='S')
	if isinstance(pdf_output, str):
		pdf_bytes = pdf_output.encode('latin-1')
	else:
		pdf_bytes = bytes(pdf_output)
	response.write(pdf_bytes)
	return response
