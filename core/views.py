from decimal import Decimal
import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib import messages
from django.conf import settings
from django.contrib.auth import get_user_model, logout
from django.core.mail import EmailMessage, get_connection
from django.core.exceptions import ValidationError
from django.http import JsonResponse, Http404
from django.shortcuts import render, redirect
from companies.models import Company
from django.db.models import Q
from django.db import connection, DatabaseError
from products.models import (
	Product,
	PriceAdjustmentBatch,
	PriceAdjustmentItem,
	Supplier,
	SupplierProductPrice,
	Brand,
	Category,
	Department,
	Volume,
	UnitOfMeasure,
	ProductGroup,
	ProductSubGroup,
)
from .middleware import ActiveCompanyMiddleware
from clients.models import Client
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.utils import timezone
from sales.models import Quote

from .forms import (
	EmailConfigurationForm,
	EmailTestForm,
	SalesConfigurationForm,
	SefazConfigurationForm,
	UserAccessProfileForm,
	UserCreateForm,
	UserPreferencesForm,
	UserProfileForm,
	ApiUserTokenForm,
)
from .models import EmailConfiguration, SalesConfiguration, SefazConfiguration, UserAccessProfile
from django.contrib.auth.decorators import user_passes_test
import jwt


PROFILE_MODULE_FIELDS = [
	'can_manage_products',
	'can_manage_clients',
	'can_manage_sales',
	'can_manage_purchases',
	'can_manage_finance',
]

SALES_PERMISSION_FIELDS = [
	'can_create_sales_records',
	'can_edit_sales_records',
	'can_delete_sales_records',
]


def _format_decimal(value, places=2):
	if value in (None, ''):
		return ''
	try:
		dec = Decimal(value)
	except Exception:
		try:
			dec = Decimal(str(value))
		except Exception:
			return str(value)
	return f'{dec:.{places}f}'


def _filter_queryset(qs, search_fields, term):
	tokens = [token for token in term.replace('%', ' ').split() if token]
	for token in tokens:
		token_filter = Q()
		for field in search_fields:
			token_filter |= Q(**{f'{field}__icontains': token})
		qs = qs.filter(token_filter)
	return qs


def _client_queryset(request):
	return Client.objects.all().order_by('first_name', 'last_name')


def _supplier_queryset(request):
	return Supplier.objects.all().order_by('name')


def _product_queryset(request):
	return Product.objects.all().order_by('name')


def _brand_queryset(request):
	return Brand.objects.all().order_by('name')


def _category_queryset(request):
	return Category.objects.all().order_by('name')


def _department_queryset(request):
	return Department.objects.all().order_by('name')


def _volume_queryset(request):
	return Volume.objects.all().order_by('description')


def _unit_queryset(request):
	return UnitOfMeasure.objects.all().order_by('code')


def _product_group_queryset(request):
	return ProductGroup.objects.all().order_by('name')


def _product_subgroup_queryset(request):
	return ProductSubGroup.objects.select_related('group', 'parent_subgroup').order_by('name')


def _quote_queryset(request):
	qs = Quote.objects.select_related('client').prefetch_related('items')
	available = getattr(request, 'available_companies', None)
	if available:
		company_ids = {company.pk for company in available if company.pk}
		if company_ids:
			qs = qs.filter(Q(company__in=company_ids) | Q(company__isnull=True))
	return qs.order_by('-created_at')


def _supplier_item_queryset(request):
	return SupplierProductPrice.objects.select_related('supplier', 'product').order_by('code')


def _serialize_client(request, client):
	name = f'{client.first_name} {client.last_name}'.strip() or client.email or client.code
	return {
		'id': str(client.pk),
		'code': client.code,
		'name': name,
		'document': client.formatted_document,
		'email': client.email,
		'label': f'{client.code} - {name}' if client.code else name,
	}


def _serialize_supplier(request, supplier):
	name = supplier.name or supplier.code
	return {
		'id': str(supplier.pk),
		'code': supplier.code,
		'name': name,
		'document': supplier.formatted_document,
		'email': supplier.email,
		'label': f'{supplier.code} - {name}' if supplier.code else name,
	}


def _serialize_brand(request, brand):
	return {
		'id': str(brand.pk),
		'name': brand.name,
		'label': brand.name,
	}


def _serialize_category(request, category):
	return {
		'id': str(category.pk),
		'name': category.name,
		'label': category.name,
	}


def _serialize_department(request, department):
	return {
		'id': str(department.pk),
		'name': department.name,
		'label': department.name,
	}


def _serialize_volume(request, volume):
	return {
		'id': str(volume.pk),
		'description': volume.description,
		'label': volume.description,
	}


def _serialize_unit(request, unit):
	return {
		'id': str(unit.pk),
		'code': unit.code,
		'name': unit.name or '',
		'label': unit.code if not unit.name else f'{unit.code} - {unit.name}',
	}


def _serialize_product_group(request, group):
	return {
		'id': str(group.pk),
		'name': group.name,
		'label': str(group),
	}


def _serialize_product_subgroup(request, subgroup):
	full_name = subgroup.full_name if hasattr(subgroup, 'full_name') else str(subgroup)
	return {
		'id': str(subgroup.pk),
		'name': subgroup.name,
		'label': full_name,
	}


def _serialize_product(request, product):
	active_company = getattr(request, 'company', None)
	stock_value = product.stock_for_company(active_company)
	label_parts = [part for part in (product.code, product.name) if part]
	return {
		'id': str(product.pk),
		'code': product.code or '',
		'name': product.name or '',
		'price': _format_decimal(product.price, 2),
		'stock': _format_decimal(stock_value, 2),
		'unit': product.unit or '',
		'cost_price': _format_decimal(product.cost_price, 4),
		'label': ' - '.join(label_parts) if label_parts else f'Produto #{product.pk}',
	}


def _serialize_quote(request, quote):
	items = getattr(quote, '_prefetched_objects_cache', {}).get('items')
	if items is None:
		items = list(quote.items.all())
	total = sum((item.total_amount for item in items), Decimal('0.00'))
	client_name = str(quote.client) if quote.client_id else ''
	return {
		'id': str(quote.pk),
		'number': quote.number or f'ORÇ-{quote.pk}',
		'client': client_name,
		'status': quote.get_status_display(),
		'valid_until': quote.valid_until.strftime('%d/%m/%Y') if quote.valid_until else '',
		'total': _format_decimal(total, 2),
		'label': f'{quote.number or quote.pk} • {client_name}'.strip(' •'),
	}


def _serialize_supplier_item(request, item):
	supplier_name = item.supplier.name if item.supplier_id else ''
	return {
		'id': str(item.pk),
		'code': item.code or '',
		'description': item.description or '',
		'supplier': supplier_name,
		'unit_price': _format_decimal(item.unit_price, 2),
		'ipi_percent': _format_decimal(item.ipi_percent, 2),
		'freight_percent': _format_decimal(item.freight_percent, 2),
		'label': ' - '.join(part for part in (item.code, item.description) if part) or f'Item #{item.pk}',
	}


LOOKUP_DEFINITIONS = {
	'clients': {
		'title': 'Selecionar cliente',
		'columns': [
			{'key': 'code', 'label': 'Código'},
			{'key': 'name', 'label': 'Nome'},
			{'key': 'document', 'label': 'Documento'},
			{'key': 'email', 'label': 'E-mail'},
		],
		'search': ['code', 'first_name', 'last_name', 'document', 'email'],
		'get_queryset': _client_queryset,
		'serialize': _serialize_client,
	},
	'suppliers': {
		'title': 'Selecionar fornecedor',
		'columns': [
			{'key': 'code', 'label': 'Código'},
			{'key': 'name', 'label': 'Nome'},
			{'key': 'document', 'label': 'Documento'},
			{'key': 'email', 'label': 'E-mail'},
		],
		'search': ['code', 'name', 'document', 'email'],
		'get_queryset': _supplier_queryset,
		'serialize': _serialize_supplier,
	},
	'brands': {
		'title': 'Selecionar marca',
		'columns': [
			{'key': 'name', 'label': 'Nome'},
		],
		'search': ['name'],
		'get_queryset': _brand_queryset,
		'serialize': _serialize_brand,
	},
	'categories': {
		'title': 'Selecionar categoria',
		'columns': [
			{'key': 'name', 'label': 'Nome'},
		],
		'search': ['name'],
		'get_queryset': _category_queryset,
		'serialize': _serialize_category,
	},
	'departments': {
		'title': 'Selecionar departamento',
		'columns': [
			{'key': 'name', 'label': 'Nome'},
		],
		'search': ['name'],
		'get_queryset': _department_queryset,
		'serialize': _serialize_department,
	},
	'volumes': {
		'title': 'Selecionar volume',
		'columns': [
			{'key': 'description', 'label': 'Descrição'},
		],
		'search': ['description'],
		'get_queryset': _volume_queryset,
		'serialize': _serialize_volume,
	},
	'units': {
		'title': 'Selecionar unidade de medida',
		'columns': [
			{'key': 'code', 'label': 'Código'},
			{'key': 'name', 'label': 'Nome'},
		],
		'search': ['code', 'name'],
		'get_queryset': _unit_queryset,
		'serialize': _serialize_unit,
	},
	'product_groups': {
		'title': 'Selecionar grupo de produtos',
		'columns': [
			{'key': 'label', 'label': 'Grupo'},
		],
		'search': ['name'],
		'get_queryset': _product_group_queryset,
		'serialize': _serialize_product_group,
	},
	'product_subgroups': {
		'title': 'Selecionar subgrupo de produtos',
		'columns': [
			{'key': 'label', 'label': 'Subgrupo'},
		],
		'search': ['name', 'parent_subgroup__name', 'group__name'],
		'get_queryset': _product_subgroup_queryset,
		'serialize': _serialize_product_subgroup,
	},
	'products': {
		'title': 'Selecionar produto',
		'columns': [
			{'key': 'code', 'label': 'Código'},
			{'key': 'name', 'label': 'Nome'},
			{'key': 'price', 'label': 'Preço'},
			{'key': 'stock', 'label': 'Estoque'},
			{'key': 'unit', 'label': 'Unidade'},
		],
		'search': ['code', 'name', 'reference', 'gtin', 'description'],
		'get_queryset': _product_queryset,
		'serialize': _serialize_product,
	},
	'quotes': {
		'title': 'Selecionar orçamento',
		'columns': [
			{'key': 'number', 'label': 'Número'},
			{'key': 'client', 'label': 'Cliente'},
			{'key': 'status', 'label': 'Status'},
			{'key': 'valid_until', 'label': 'Validade'},
			{'key': 'total', 'label': 'Total'},
		],
		'search': ['number', 'client__first_name', 'client__last_name', 'client__code'],
		'get_queryset': _quote_queryset,
		'serialize': _serialize_quote,
	},
	'supplier_items': {
		'title': 'Selecionar item do fornecedor',
		'columns': [
			{'key': 'code', 'label': 'Código'},
			{'key': 'description', 'label': 'Descrição'},
			{'key': 'supplier', 'label': 'Fornecedor'},
			{'key': 'unit_price', 'label': 'Preço compra'},
			{'key': 'ipi_percent', 'label': 'IPI %'},
			{'key': 'freight_percent', 'label': 'Frete %'},
		],
		'search': ['code', 'description', 'supplier__name', 'product__name'],
		'get_queryset': _supplier_item_queryset,
		'serialize': _serialize_supplier_item,
		'limit': 30,
	},
}


def _lookup_limit(request, default=20):
	try:
		limit = int(request.GET.get('limit', default))
	except (TypeError, ValueError):
		return default
	return max(1, min(limit, 50))


@login_required
def lookup_records(request, slug):
	config = LOOKUP_DEFINITIONS.get(slug)
	if not config:
		raise Http404('Lookup não disponível.')

	qs = config['get_queryset'](request)
	term = (request.GET.get('q') or '').strip()
	if term:
		qs = _filter_queryset(qs, config.get('search', []), term)

	limit = _lookup_limit(request, default=config.get('limit', 20))
	results = []
	for record in qs[:limit]:
		results.append(config['serialize'](request, record))

	return JsonResponse({
		'results': results,
		'columns': config['columns'],
		'title': config.get('title', 'Pesquisar'),
	})


def _profile_field_groups(form):
	return {
		'module_fields': [form[field_name] for field_name in PROFILE_MODULE_FIELDS],
		'sales_permission_fields': [form[field_name] for field_name in SALES_PERMISSION_FIELDS],
	}


@login_required
def dashboard(request):
	# Dense table preference: GET overrides cookie
	if 'dense' in request.GET:
		dense_param = (request.GET.get('dense') or '').strip().lower()
		dense = dense_param in ('1', 'true', 'yes', 'y', 'on')
	else:
		dense_cookie = (request.COOKIES.get('pref_dense') or '').strip().lower()
		dense = dense_cookie in ('1', 'true', 'yes', 'y', 'on')

	total_products = Product.objects.count()
	total_clients = Client.objects.count()
	recent_products = Product.objects.order_by('-created_at')[:5]
	recent_clients = Client.objects.order_by('-created_at')[:5]
	pending_adjustments_qs = PriceAdjustmentItem.objects.select_related('product', 'batch').filter(
		status=PriceAdjustmentItem.Status.PENDING
	).order_by('-batch__created_at', 'product__name')
	pending_adjustments_total = pending_adjustments_qs.count()
	pending_adjustments = list(pending_adjustments_qs[:8])
	pending_batches_total = PriceAdjustmentBatch.objects.filter(status=PriceAdjustmentBatch.Status.PENDING).count()
	response = render(request, 'core/dashboard.html', {
		'total_products': total_products,
		'total_clients': total_clients,
		'recent_products': recent_products,
		'recent_clients': recent_clients,
		'pending_adjustments': pending_adjustments,
		'pending_adjustments_total': pending_adjustments_total,
		'pending_batches_total': pending_batches_total,
		'dense': dense,
	})
	if 'dense' in request.GET:
		response.set_cookie('pref_dense', '1' if dense else '0', max_age=60*60*24*365)
	return response

# Create your views here.


def home(request):
	# compatibility: redirect to dashboard if authenticated, otherwise to login
	from django.shortcuts import redirect
	if request.user.is_authenticated:
		return redirect('dashboard')
	return redirect('login')


@login_required
def sefaz_settings(request):
	config = SefazConfiguration.load()
	if request.method == 'POST':
		form = SefazConfigurationForm(request.POST, request.FILES, instance=config)
		if form.is_valid():
			cfg = form.save(commit=False)
			cfg.updated_by = request.user
			try:
				cfg.save()
			except ValidationError as exc:
				for field, messages_list in exc.message_dict.items():
					if field in form.fields:
						for message in messages_list:
							form.add_error(field, message)
					else:
						for message in messages_list:
							form.add_error(None, message)
			else:
				messages.success(request, 'Configuração da SEFAZ atualizada.')
				return redirect(reverse('core:settings_sefaz'))
	else:
		form = SefazConfigurationForm(instance=config)
	return render(request, 'core/sefaz_settings.html', {
		'form': form,
		'config': config,
	})


@login_required
def sales_settings(request):
	config = SalesConfiguration.load()
	if request.method == 'POST':
		form = SalesConfigurationForm(request.POST, instance=config)
		if form.is_valid():
			cfg = form.save(commit=False)
			cfg.updated_by = request.user
			cfg.save()
			messages.success(request, 'Configurações de vendas atualizadas.')
			return redirect(reverse('core:settings_sales'))
	else:
		form = SalesConfigurationForm(instance=config)
	return render(request, 'core/sales_settings.html', {
		'form': form,
		'config': config,
	})


@login_required
def email_settings(request):
	config = EmailConfiguration.load()
	test_form = EmailTestForm()
	if request.method == 'POST':
		action = request.POST.get('action', 'save')
		if action == 'test':
			form = EmailConfigurationForm(instance=config)
			test_form = EmailTestForm(request.POST)
			if test_form.is_valid():
				if not config.smtp_host:
					test_form.add_error(None, 'Configure o servidor SMTP antes de enviar um teste.')
				else:
					from_email = (
						config.default_from_email
						or getattr(settings, 'DEFAULT_FROM_EMAIL', '')
						or config.smtp_username
						or 'no-reply@localhost'
					)
					try:
						connection = get_connection(
							backend='django.core.mail.backends.smtp.EmailBackend',
							host=config.smtp_host,
							port=config.smtp_port,
							username=config.smtp_username or None,
							password=config.smtp_password or None,
							use_tls=config.smtp_use_tls,
							use_ssl=config.smtp_use_ssl,
							timeout=15,
						)
						email = EmailMessage(
							subject='Teste de configuração de e-mail',
							body=(
								'E-mail enviado automaticamente para validar sua configuração SMTP.\n\n'
								f'Solicitado por: {request.user.get_full_name() or request.user.username}\n'
								f'Data/Hora: {timezone.localtime():%d/%m/%Y %H:%M:%S}\n'
								f'Host: {config.smtp_host}:{config.smtp_port}\n'
							),
							from_email=from_email,
							to=[test_form.cleaned_data['recipient']],
							connection=connection,
						)
						email.send(fail_silently=False)
					except Exception as exc:
						test_form.add_error(None, f'Não foi possível enviar o e-mail de teste: {exc}')
					else:
						messages.success(request, 'E-mail de teste enviado com sucesso.')
						return redirect(reverse('core:settings_email'))
		else:
			form = EmailConfigurationForm(request.POST, instance=config)
			if form.is_valid():
				cfg = form.save(commit=False)
				cfg.updated_by = request.user
				cfg.save()
				messages.success(request, 'Configurações de e-mail atualizadas.')
				return redirect(reverse('core:settings_email'))
	else:
		form = EmailConfigurationForm(instance=config)
	return render(request, 'core/email_settings.html', {
		'form': form,
		'config': config,
		'test_form': test_form,
	})


@login_required
def access_settings_list(request):
	User = get_user_model()
	profiles = []
	for user in User.objects.all().order_by('first_name', 'last_name', 'username'):
		profile, _ = UserAccessProfile.objects.get_or_create(user=user)
		profiles.append(profile)
	return render(request, 'core/access_settings_list.html', {
		'profiles': profiles,
	})


@login_required
def access_settings_create(request):
	if request.method == 'POST':
		user_form = UserCreateForm(request.POST)
		profile_form = UserAccessProfileForm(request.POST)
		if user_form.is_valid() and profile_form.is_valid():
			user = user_form.save()
			profile = profile_form.save(commit=False)
			profile.user = user
			profile.updated_by = request.user
			profile.save()
			profile_form.instance = profile
			profile_form.save_m2m()
			messages.success(request, f'Usuário "{user.get_full_name() or user.username}" cadastrado com sucesso.')
			return redirect('core:settings_access')
	else:
		user_form = UserCreateForm()
		profile_form = UserAccessProfileForm()
	return render(request, 'core/access_settings_create.html', {
		'user_form': user_form,
		'profile_form': profile_form,
		**_profile_field_groups(profile_form),
	})


@login_required
def access_settings_edit(request, user_id):
	profile, _ = UserAccessProfile.objects.get_or_create(user_id=user_id)
	if request.method == 'POST':
		form = UserAccessProfileForm(request.POST, instance=profile)
		if form.is_valid():
			profile = form.save(commit=False)
			profile.updated_by = request.user
			profile.save()
			form.save_m2m()
			messages.success(request, 'Permissões atualizadas.')
			return redirect('core:settings_access')
	else:
		form = UserAccessProfileForm(instance=profile)
	return render(request, 'core/access_settings_edit.html', {
		'form': form,
		'profile': profile,
		**_profile_field_groups(form),
	})


def _hash_api_password(password: str, iterations: int = 240000) -> str:
	salt = secrets.token_hex(16)
	dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), iterations)
	return f"pbkdf2_sha256${iterations}${salt}${base64.b64encode(dk).decode('ascii')}"


def _create_api_token(user_id: int, username: str, vendor_code: str | None = None) -> tuple[str, datetime]:
	secret = os.getenv("JWT_SECRET", "change-me")
	algorithm = os.getenv("JWT_ALGORITHM", "HS256")
	expires_minutes = int(os.getenv("JWT_EXPIRES_MINUTES", "60"))
	now = datetime.now(dt_timezone.utc)
	exp = now + timedelta(minutes=expires_minutes)
	payload = {
		"sub": str(user_id),
		"username": username,
		"exp": exp,
		"iat": now,
	}
	if vendor_code:
		payload["vendor_code"] = vendor_code
	return jwt.encode(payload, secret, algorithm=algorithm), exp


def _list_api_users():
	try:
		with connection.cursor() as cursor:
			cursor.execute(
				"""
				SELECT id, username, vendor_code, is_active, created_at, updated_at
				FROM api_users
				ORDER BY username;
				"""
			)
			rows = cursor.fetchall()
	except DatabaseError:
		return []
	return [
		{
			"id": row[0],
			"username": row[1],
			"vendor_code": row[2],
			"is_active": row[3],
			"created_at": row[4],
			"updated_at": row[5],
		}
		for row in rows
	]


def _get_api_user(user_id: int):
	with connection.cursor() as cursor:
		cursor.execute(
			"""
			SELECT id, username, vendor_code, is_active, created_at, updated_at
			FROM api_users
			WHERE id = %s;
			""",
			[user_id],
		)
		row = cursor.fetchone()
	if not row:
		raise Http404()
	return {
		"id": row[0],
		"username": row[1],
		"vendor_code": row[2],
		"is_active": row[3],
		"created_at": row[4],
		"updated_at": row[5],
	}


@login_required
@user_passes_test(lambda u: u.is_superuser)
def api_user_tokens(request):
	token = None
	expires_at = None
	user_data = None
	users = _list_api_users()
	if request.method == 'POST':
		form = ApiUserTokenForm(request.POST)
		if form.is_valid():
			username = form.cleaned_data['username'].strip()
			password = form.cleaned_data['password']
			vendor_code = (form.cleaned_data.get('vendor_code') or '').strip() or None
			is_active = bool(form.cleaned_data.get('is_active'))
			if not password:
				form.add_error('password', 'Informe a senha para gerar o token.')
			else:
				password_hash = _hash_api_password(password)
				try:
					with connection.cursor() as cursor:
						cursor.execute(
							"""
							INSERT INTO api_users (username, password_hash, vendor_code, is_active)
							VALUES (%s, %s, %s, %s)
							ON CONFLICT (username) DO UPDATE SET
								password_hash = EXCLUDED.password_hash,
								vendor_code = EXCLUDED.vendor_code,
								is_active = EXCLUDED.is_active
							RETURNING id, username, is_active, created_at, updated_at, vendor_code;
							""",
							[username, password_hash, vendor_code, is_active],
						)
						row = cursor.fetchone()
				except DatabaseError as exc:
					messages.error(request, f'Falha ao gravar usuário na API: {exc}')
				else:
					token, expires_at = _create_api_token(row[0], row[1], row[5])
					user_data = {
						"id": row[0],
						"username": row[1],
						"is_active": row[2],
						"created_at": row[3],
						"updated_at": row[4],
						"vendor_code": row[5],
					}
					users = _list_api_users()
					messages.success(request, 'Usuário criado/atualizado e token gerado.')
	else:
		form = ApiUserTokenForm()

	return render(request, 'core/api_user_tokens.html', {
		'form': form,
		'token': token,
		'expires_at': expires_at,
		'user_data': user_data,
		'users': users,
		'editing': False,
	})


@login_required
@user_passes_test(lambda u: u.is_superuser)
def api_user_edit(request, user_id):
	token = None
	expires_at = None
	user_data = None
	users = _list_api_users()
	api_user = _get_api_user(user_id)
	if request.method == 'POST':
		form = ApiUserTokenForm(request.POST)
		if form.is_valid():
			username = form.cleaned_data['username'].strip()
			password = form.cleaned_data['password']
			vendor_code = (form.cleaned_data.get('vendor_code') or '').strip() or None
			is_active = bool(form.cleaned_data.get('is_active'))
			password_hash = _hash_api_password(password) if password else None
			try:
				with connection.cursor() as cursor:
					cursor.execute(
						"""
						UPDATE api_users
						SET username = %s,
							password_hash = COALESCE(%s, password_hash),
							vendor_code = %s,
							is_active = %s
						WHERE id = %s
						RETURNING id, username, is_active, created_at, updated_at, vendor_code;
						""",
						[username, password_hash, vendor_code, is_active, user_id],
					)
					row = cursor.fetchone()
			except DatabaseError as exc:
				messages.error(request, f'Falha ao atualizar usuário da API: {exc}')
			else:
				token, expires_at = _create_api_token(row[0], row[1], row[5])
				user_data = {
					"id": row[0],
					"username": row[1],
					"is_active": row[2],
					"created_at": row[3],
					"updated_at": row[4],
					"vendor_code": row[5],
				}
				users = _list_api_users()
				messages.success(request, 'Usuário atualizado e token gerado.')
	else:
		form = ApiUserTokenForm(initial={
			"username": api_user["username"],
			"vendor_code": api_user["vendor_code"] or "",
			"is_active": api_user["is_active"],
		})

	return render(request, 'core/api_user_tokens.html', {
		'form': form,
		'token': token,
		'expires_at': expires_at,
		'user_data': user_data or api_user,
		'users': users,
		'editing': True,
		'editing_user': api_user,
	})


@login_required
def profile_settings(request):
	profile, _ = UserAccessProfile.objects.get_or_create(user=request.user)
	if request.method == 'POST':
		user_form = UserProfileForm(request.POST, instance=request.user)
		preferences_form = UserPreferencesForm(request.POST, request.FILES, instance=profile)
		if user_form.is_valid() and preferences_form.is_valid():
			user_form.save()
			profile_instance = preferences_form.save(commit=False)
			profile_instance.updated_by = request.user
			profile_instance.save()
			messages.success(request, 'Perfil atualizado com sucesso.')
			return redirect('core:settings_profile')
	else:
		user_form = UserProfileForm(instance=request.user)
		full_name = (request.user.get_full_name() or '').strip() or request.user.username
		display_initial = profile.display_name or full_name
		preferences_form = UserPreferencesForm(instance=profile, initial={'display_name': display_initial})
	return render(request, 'core/profile_settings.html', {
		'user_form': user_form,
		'preferences_form': preferences_form,
		'profile': profile,
	})


@login_required
def logout_view(request):
	if request.method == 'POST':
		logout(request)
		messages.success(request, 'Sessão encerrada com sucesso.')
		return redirect('login')
	return redirect('dashboard')


@login_required
def switch_company(request):
	if request.method != 'POST':
		return redirect('dashboard')
	company_id = request.POST.get('company_id')
	next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'dashboard'
	if company_id:
		try:
			company_id = int(company_id)
		except (TypeError, ValueError):
			company_id = None
		available_ids = {c.pk for c in getattr(request, 'available_companies', [])}
		if company_id in available_ids:
			request.session[ActiveCompanyMiddleware.session_key] = company_id
			messages.success(request, 'Empresa ativa atualizada.')
		else:
			messages.error(request, 'Você não tem acesso à empresa selecionada.')
	return redirect(next_url)
