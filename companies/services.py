from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import requests
from django.conf import settings
from django.utils import timezone

from core.models import SefazConfiguration
from core.sefaz.distribution import (
	NFeCertificateError,
	NFeDistributionError,
	NFeDistributionResult,
	consult_nfe_distribution,
)
from core.utils.documents import normalize_cnpj, format_cnpj


class SefazAPIError(Exception):
	"""Raised when the SEFAZ API cannot return data for a CNPJ."""


def _pick(data: Dict[str, Any], *keys: str) -> Optional[Any]:
	for key in keys:
		if key in data and data[key] not in (None, ''):
			return data[key]
	return None


def _first_non_empty(values):
	for value in values:
		if isinstance(value, str):
			if value.strip():
				return value.strip()
		elif value not in (None, '', [], {}):
			return value
	return None


def _format_phone(area_code: Optional[str], number: Optional[str]) -> str:
	if not number:
		return ''
	number = str(number).strip()
	if not number:
		return ''
	area_code = (area_code or '').strip()
	if area_code and not number.startswith('('):
		return f'({area_code}) {number}'
	return number


def _extract_state_registration(establishment: Dict[str, Any]) -> str:
	if not isinstance(establishment, dict):
		return ''
	insc = _pick(establishment, 'inscricao_estadual', 'ie')
	if insc:
		return insc
	registrations = establishment.get('inscricoes_estaduais')
	if isinstance(registrations, list):
		def _score(entry: Dict[str, Any]) -> int:
			if not isinstance(entry, dict):
				return -1
			if str(entry.get('ativo', '')).upper() in ('1', 'TRUE', 'SIM', 'S', 'ATIVO', 'ATIVA'):
				return 2
			if str(entry.get('principal', '')).upper() in ('1', 'TRUE', 'SIM', 'S'):
				return 1
			return 0

		best_entry = None
		best_score = -1
		for entry in registrations:
			if not isinstance(entry, dict):
				continue
			score = _score(entry)
			if score > best_score:
				best_entry = entry
				best_score = score
		if isinstance(best_entry, dict):
			return best_entry.get('inscricao_estadual') or best_entry.get('numero') or ''
	return ''


def _safe_upper(value: Optional[str]) -> str:
	if not isinstance(value, str):
		return ''
	return value.upper()


def fetch_company_data_from_sefaz(cnpj: str) -> Dict[str, Any]:
	"""Fetch company information from the configured SEFAZ API."""
	clean_cnpj = normalize_cnpj(cnpj)
	if len(clean_cnpj) != 14:
		raise ValueError('CNPJ inválido.')

	config = None
	try:
		config = SefazConfiguration.load()
	except Exception:
		config = None

	base_url = ''
	token = ''
	timeout = None
	if config:
		base_url = (config.base_url or '').strip()
		token = (config.token or '').strip()
		timeout = config.timeout

	if not base_url:
		base_url = getattr(settings, 'SEFAZ_API_BASE_URL', '').strip()
	if not base_url:
		raise SefazAPIError('SEFAZ API não está configurada.')

	if timeout in (None, 0):
		timeout = getattr(settings, 'SEFAZ_API_TIMEOUT', 10)
	if not token:
		token = getattr(settings, 'SEFAZ_API_TOKEN', '').strip()
	url = f"{base_url.rstrip('/')}/cnpj/{clean_cnpj}"

	headers = {'Accept': 'application/json'}
	if token:
		headers['Authorization'] = f"Bearer {token}"

	try:
		response = requests.get(url, headers=headers, timeout=timeout)
	except requests.RequestException as exc:  # pragma: no cover - network errors simulated in tests
		raise SefazAPIError('Não foi possível conectar à SEFAZ.') from exc

	if response.status_code == 404:
		raise SefazAPIError('CNPJ não encontrado na SEFAZ.')
	if response.status_code >= 400:
		raise SefazAPIError(f'Erro ao consultar SEFAZ (status {response.status_code}).')

	try:
		payload = response.json()
	except ValueError as exc:
		raise SefazAPIError('Resposta inválida da SEFAZ.') from exc

	data = payload if isinstance(payload, dict) else {}
	establishment = data.get('estabelecimento') if isinstance(data.get('estabelecimento'), dict) else {}
	city_data = establishment.get('cidade') if isinstance(establishment.get('cidade'), dict) else {}
	state_data = establishment.get('estado') if isinstance(establishment.get('estado'), dict) else {}

	status = _safe_upper(
		_first_non_empty([
			_pick(data, 'situacao', 'status', 'situacao_cadastral'),
			_pick(establishment, 'situacao', 'status', 'situacao_cadastral'),
		])
	)
	is_active = status in ('ATIVA', 'HABILITADO', 'REGULAR')

	address_value = _pick(establishment, 'logradouro', 'endereco')
	if not address_value:
		address_value = ' '.join(filter(None, [
			(establishment.get('tipo_logradouro') or '').strip() or None,
			(establishment.get('logradouro') or '').strip() or None,
		])).strip()

	phone_value = _first_non_empty([
		_format_phone(establishment.get('ddd1'), establishment.get('telefone1')),
		_format_phone(establishment.get('ddd2'), establishment.get('telefone2')),
		_pick(establishment, 'telefone', 'contato_telefone', 'fone'),
		_pick(data, 'telefone', 'contato_telefone', 'fone'),
	])

	website_value = _first_non_empty([
		_pick(establishment, 'site', 'website'),
		_pick(data, 'website', 'site'),
	])

	email_value = _first_non_empty([
		_pick(establishment, 'email', 'contato_email'),
		_pick(data, 'email', 'contato_email'),
	])

	city_value = _first_non_empty([
		_pick(establishment, 'municipio', 'cidade'),
		city_data.get('nome') if isinstance(city_data, dict) else None,
		_pick(data, 'municipio', 'cidade'),
	])
	if isinstance(city_value, dict):
		city_value = _first_non_empty([
			city_value.get('nome'),
			city_value.get('name'),
			city_value.get('descricao'),
		])
	if city_value is None:
		city_value = ''
	elif not isinstance(city_value, str):
		city_value = str(city_value)

	return {
		'code': _pick(data, 'codigo_empresa', 'codigo', 'cod') or clean_cnpj,
		'name': _pick(data, 'razao_social', 'nome_empresarial', 'nome') or _pick(establishment, 'razao_social') or '',
		'trade_name': _first_non_empty([
			_pick(data, 'nome_fantasia', 'fantasia'),
			_pick(establishment, 'nome_fantasia', 'fantasia'),
		]) or '',
		'tax_id': format_cnpj(_pick(data, 'cnpj', 'documento', 'numero_cnpj') or clean_cnpj),
		'state_registration': _first_non_empty([
			_pick(data, 'inscricao_estadual', 'ie', 'inscricao_estadual_atual'),
			_extract_state_registration(establishment),
		]) or '',
		'email': email_value or '',
		'phone': phone_value or '',
		'website': website_value or '',
		'address': address_value or _pick(data, 'logradouro', 'endereco') or '',
		'number': _pick(establishment, 'numero', 'nr') or _pick(data, 'numero', 'nr') or '',
		'complement': _pick(establishment, 'complemento') or _pick(data, 'complemento') or '',
		'district': _pick(establishment, 'bairro') or _pick(data, 'bairro') or '',
		'city': city_value,
		'state': _safe_upper(_first_non_empty([
			_pick(establishment, 'uf'),
			state_data.get('sigla') if isinstance(state_data, dict) else None,
			_pick(data, 'uf', 'estado'),
		])),
		'zip_code': _first_non_empty([
			_pick(establishment, 'cep', 'codigo_cep'),
			_pick(data, 'cep', 'codigo_cep'),
		]) or '',
		'notes': _first_non_empty([
			_pick(establishment, 'observacoes', 'notes'),
			_pick(data, 'observacoes', 'notes'),
		]) or '',
		'is_active': is_active,
	}


__all__ = [
	'fetch_company_data_from_sefaz',
	'normalize_cnpj',
	'format_cnpj',
	'SefazAPIError',
	'fetch_nfe_documents_for_cnpj',
	'NFeDistributionError',
	'NFeDistributionResult',
	'has_configured_sefaz_certificate',
	'prepare_company_nfe_query',
	'serialize_nfe_document',
]


def _digits_only(value: str) -> str:
	return ''.join(ch for ch in value if ch.isdigit())


_UF_TO_CUF = {
	'AC': '12',
	'AL': '27',
	'AM': '13',
	'AP': '16',
	'BA': '29',
	'CE': '23',
	'DF': '53',
	'ES': '32',
	'GO': '52',
	'MA': '21',
	'MG': '31',
	'MS': '50',
	'MT': '51',
	'PA': '15',
	'PB': '25',
	'PE': '26',
	'PI': '22',
	'PR': '41',
	'RJ': '33',
	'RN': '24',
	'RO': '11',
	'RR': '14',
	'RS': '43',
	'SC': '42',
	'SE': '28',
	'SP': '35',
	'TO': '17',
}


def _resolve_company_state_code(company: 'Company') -> str:
	uf = (getattr(company, 'state', '') or '').upper()
	return _UF_TO_CUF.get(uf, '91')


def has_configured_sefaz_certificate(config: Optional[SefazConfiguration] = None) -> bool:
	if config is None:
		try:
			config = SefazConfiguration.load()
		except Exception:
			config = None
	return bool(
		config
		and getattr(config, 'certificate_file', None)
		and getattr(config, 'certificate_password', '')
	)


def fetch_nfe_documents_for_cnpj(
	cnpj: str,
	*,
	state_code: str = '91',
	last_nsu: Optional[str] = None,
	nsu: Optional[str] = None,
	access_key: Optional[str] = None,
) -> NFeDistributionResult:
	"""Consult NF-e documents issued against the informed CNPJ using the configured A1 certificate."""
	clean_cnpj = normalize_cnpj(cnpj)
	if len(clean_cnpj) != 14:
		raise ValueError('CNPJ inválido.')

	config = SefazConfiguration.load()
	if not config:
		raise NFeDistributionError('Configuração SEFAZ não encontrada.')

	try:
		return consult_nfe_distribution(
			config=config,
			cnpj=clean_cnpj,
			state_code=state_code,
			last_nsu=last_nsu,
			nsu=nsu,
			access_key=access_key,
		)
	except NFeCertificateError as exc:
		raise NFeDistributionError(str(exc)) from exc
	except NFeDistributionError as exc:
		message = str(exc)
		if state_code != '91' and '404' in message:
			fallback = consult_nfe_distribution(
				config=config,
				cnpj=clean_cnpj,
				state_code='91',
				last_nsu=last_nsu,
				nsu=nsu,
				access_key=access_key,
			)
			return fallback
		raise


def prepare_company_nfe_query(
	company: 'Company',
	params: Dict[str, Optional[str]],
) -> Tuple[Dict[str, str], Optional[NFeDistributionResult], Optional[str], bool]:
	"""Shared helper to evaluate SEFAZ readiness and run a distribution query."""
	config = SefazConfiguration.load()
	sefaz_ready = has_configured_sefaz_certificate(config)

	sanitized_params = {
		'last_nsu': (params.get('last_nsu') or '').strip(),
		'nsu': (params.get('nsu') or '').strip(),
		'access_key': (params.get('access_key') or '').strip(),
		'issued_from': (params.get('issued_from') or '').strip(),
		'issued_until': (params.get('issued_until') or '').strip(),
		'authorized_from': (params.get('authorized_from') or '').strip(),
		'authorized_until': (params.get('authorized_until') or '').strip(),
	}

	if not sefaz_ready:
		return sanitized_params, None, 'Certificado digital A1 não configurado. Atualize as configurações da SEFAZ.', sefaz_ready

	state_code = _resolve_company_state_code(company)
	try:
		raw_access_key = sanitized_params['access_key']
		raw_nsu = sanitized_params['nsu']
		raw_last_nsu = sanitized_params['last_nsu']

		if raw_access_key:
			access_key = _digits_only(raw_access_key)
			sanitized_params['access_key'] = access_key
			if len(access_key) != 44:
				raise ValueError('A chave de acesso deve conter 44 dígitos.')
			result = fetch_nfe_documents_for_cnpj(company.tax_id, state_code=state_code, access_key=access_key)
		elif raw_nsu:
			nsu = _digits_only(raw_nsu)
			sanitized_params['nsu'] = nsu
			if not nsu:
				raise ValueError('Informe um NSU válido.')
			if len(nsu) > 15:
				raise ValueError('O NSU deve ter no máximo 15 dígitos.')
			result = fetch_nfe_documents_for_cnpj(company.tax_id, state_code=state_code, nsu=nsu)
		else:
			last_nsu = _digits_only(raw_last_nsu)
			sanitized_params['last_nsu'] = last_nsu
			result = fetch_nfe_documents_for_cnpj(company.tax_id, state_code=state_code, last_nsu=last_nsu or None)
	except ValueError as exc:
		return sanitized_params, None, str(exc), sefaz_ready
	except NFeDistributionError as exc:
		return sanitized_params, None, str(exc), sefaz_ready

	try:
		result = _filter_result_by_dates(result, sanitized_params)
	except ValueError as exc:
		return sanitized_params, None, str(exc), sefaz_ready
	return sanitized_params, result, None, sefaz_ready


def serialize_nfe_document(doc) -> Dict[str, Optional[str]]:
	return {
		'nsu': doc.nsu,
		'schema': doc.schema,
		'document_type': doc.document_type,
		'access_key': doc.access_key,
		'issuer_tax_id': doc.issuer_tax_id,
		'issuer_name': doc.issuer_name,
		'issue_datetime': doc.issue_datetime.isoformat() if doc.issue_datetime else None,
		'authorization_datetime': doc.authorization_datetime.isoformat() if doc.authorization_datetime else None,
		'total_value': str(doc.total_value) if doc.total_value is not None else None,
		'raw_xml': doc.raw_xml,
	}


def _parse_datetime(value: str) -> Optional[datetime]:
	if not value:
		return None
	try:
		dt = datetime.fromisoformat(value)
	except ValueError:
		try:
			dt = datetime.strptime(value, '%Y-%m-%d')
		except ValueError as exc:
			raise ValueError('Use o formato ISO 8601 (AAAA-MM-DD ou AAAA-MM-DDTHH:MM[:SS]).') from exc
	if timezone.is_naive(dt):
		dt = timezone.make_aware(dt, timezone.get_current_timezone())
	return dt


def _filter_result_by_dates(result: Optional[NFeDistributionResult], params: Dict[str, str]) -> Optional[NFeDistributionResult]:
	if not result:
		return result

	issued_from = _parse_datetime(params.get('issued_from', '')) if params.get('issued_from') else None
	issued_until = _parse_datetime(params.get('issued_until', '')) if params.get('issued_until') else None
	auth_from = _parse_datetime(params.get('authorized_from', '')) if params.get('authorized_from') else None
	auth_until = _parse_datetime(params.get('authorized_until', '')) if params.get('authorized_until') else None

	if not any([issued_from, issued_until, auth_from, auth_until]):
		return result

	filtered_docs = []
	for doc in result.documents:
		if issued_from and (not doc.issue_datetime or doc.issue_datetime < issued_from):
			continue
		if issued_until and (not doc.issue_datetime or doc.issue_datetime > issued_until):
			continue
		if auth_from and (not doc.authorization_datetime or doc.authorization_datetime < auth_from):
			continue
		if auth_until and (not doc.authorization_datetime or doc.authorization_datetime > auth_until):
			continue
		filtered_docs.append(doc)

	return NFeDistributionResult(
		status_code=result.status_code,
		status_message=result.status_message,
		last_nsu=result.last_nsu,
		max_nsu=result.max_nsu,
		documents=filtered_docs,
	)
