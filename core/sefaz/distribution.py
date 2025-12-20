from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import logging
from typing import Iterable, List, Optional
import xml.etree.ElementTree as ET
import zlib

import requests
from django.conf import settings
from django.utils import timezone

from core.models import SefazConfiguration
from core.utils.certificates import (
	CertificateBundle,
	CertificateError,
	load_pkcs12_from_path,
	temporary_certificate_files,
)
from core.utils.documents import normalize_cnpj


logger = logging.getLogger(__name__)


class NFeDistributionError(Exception):
	"""Raised when SEFAZ distribution service cannot be consulted."""


class NFeCertificateError(NFeDistributionError):
	"""Raised when there is no valid certificate configured."""


@dataclass(slots=True)
class NFeDocumentSummary:
	nsu: str
	schema: str
	document_type: str
	access_key: str
	issuer_tax_id: str
	issuer_name: str
	issue_datetime: Optional[datetime]
	authorization_datetime: Optional[datetime]
	total_value: Optional[Decimal]
	raw_xml: str


@dataclass(slots=True)
class NFeDistributionResult:
	status_code: str
	status_message: str
	last_nsu: str
	max_nsu: str
	documents: List[NFeDocumentSummary]


_ENDPOINTS = {
	SefazConfiguration.Environment.PRODUCTION: (
		'https://www1.nfe.fazenda.gov.br/ws/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx',
		'https://www.nfe.fazenda.gov.br/ws/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx',
		'https://nfe.svrs.rs.gov.br/ws/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx',
	),
	SefazConfiguration.Environment.HOMOLOGATION: (
		'https://hom.nfe.fazenda.gov.br/ws/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx',
		'https://nfe-homologacao.svrs.rs.gov.br/ws/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx',
	),
}

_SOAP_NAMESPACE = 'http://www.w3.org/2003/05/soap-envelope'
_WSDL_NAMESPACE = 'http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe'
_NFE_NAMESPACE = 'http://www.portalfiscal.inf.br/nfe'


def _unique_endpoints(values: Iterable[str]) -> List[str]:
	seen = set()
	ordered: List[str] = []
	for value in values:
		sanitized = (value or '').strip()
		if not sanitized:
			continue
		if sanitized.endswith('?wsdl'):
			sanitized = sanitized[:-5]
		if sanitized not in seen:
			ordered.append(sanitized)
			seen.add(sanitized)
	return ordered


def _get_endpoints(config: SefazConfiguration) -> List[str]:
	defaults = _ENDPOINTS.get(
		config.environment,
		_ENDPOINTS[SefazConfiguration.Environment.PRODUCTION],
	)
	return _unique_endpoints(defaults)


def _load_certificate(config: SefazConfiguration) -> CertificateBundle:
	if not config.certificate_file:
		raise NFeCertificateError('Nenhum certificado digital cadastrado.')
	if not config.certificate_password:
		raise NFeCertificateError('Informe a senha do certificado nas configurações.')
	try:
		return load_pkcs12_from_path(config.certificate_file.path, config.certificate_password)
	except CertificateError as exc:
		raise NFeCertificateError(str(exc)) from exc


def _soap_envelope(content: str) -> str:
	return (
		'<?xml version="1.0" encoding="utf-8"?>'
		f'<soap12:Envelope xmlns:soap12="{_SOAP_NAMESPACE}">'
		f'<soap12:Header>'
		f'<nfeCabecMsg xmlns="{_WSDL_NAMESPACE}">'
		f'<cUF>91</cUF>'
		f'<versaoDados>1.01</versaoDados>'
		f'</nfeCabecMsg>'
		f'</soap12:Header>'
		f'<soap12:Body>'
		f'<nfeDadosMsg xmlns="{_WSDL_NAMESPACE}">{content}</nfeDadosMsg>'
		f'</soap12:Body>'
		f'</soap12:Envelope>'
	)


def _build_distdfe_payload(
	cnpj: str,
	environment: str,
	*,
	state_code: str,
	last_nsu: Optional[str],
	nsu: Optional[str],
	access_key: Optional[str],
) -> str:
	tp_amb = '1' if environment == SefazConfiguration.Environment.PRODUCTION else '2'
	cnpj_digits = normalize_cnpj(cnpj)
	if len(cnpj_digits) != 14:
		raise ValueError('CNPJ inválido para consulta NF-e.')

	cuf = state_code or '91'
	if not cuf.isdigit() or len(cuf) not in (2,):
		cuf = '91'

	if access_key:
		payload_inner = f'<consChNFe><chNFe>{access_key}</chNFe></consChNFe>'
	elif nsu:
		nsu_value = nsu.zfill(15)
		payload_inner = f'<consNSU><NSU>{nsu_value}</NSU></consNSU>'
	else:
		ult_nsu_value = (last_nsu or '000000000000000').zfill(15)
		payload_inner = f'<distNSU><ultNSU>{ult_nsu_value}</ultNSU></distNSU>'

	body = (
		f'<distDFeInt xmlns="{_NFE_NAMESPACE}" versao="1.01">'
		f'<tpAmb>{tp_amb}</tpAmb>'
		f'<cUFAutor>{cuf}</cUFAutor>'
		f'<CNPJ>{cnpj_digits}</CNPJ>'
		f'{payload_inner}'
		f'</distDFeInt>'
	)
	return _soap_envelope(body)


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
	if not value:
		return None
	try:
		# Python 3.12 supports fromisoformat with timezone offset
		dt = datetime.fromisoformat(value)
	except ValueError:
		return None
	if timezone.is_naive(dt):
		return timezone.make_aware(dt, timezone=timezone.utc)
	return dt


def _safe_decimal(value: Optional[str]) -> Optional[Decimal]:
	if not value:
		return None
	try:
		return Decimal(value)
	except Exception:
		return None


def _decompress_doczip(content: str) -> ET.Element:
	raw = base64.b64decode(content)
	try:
		xml_bytes = zlib.decompress(raw, 15 + 32)
	except zlib.error:
		xml_bytes = raw  # fallback if already plain xml
	return ET.fromstring(xml_bytes.decode('utf-8'))


def _parse_document(element: ET.Element, nsu: str, schema: str) -> NFeDocumentSummary:
	tag = element.tag.split('}', 1)[-1]
	get = lambda name: element.findtext(f'.//{{{_NFE_NAMESPACE}}}{name}')

	access_key = get('chNFe') or ''
	issuer_tax_id = get('CNPJ') or ''
	issuer_name = get('xNome') or ''
	if issuer_tax_id:
		try:
			issuer_tax_id = normalize_cnpj(issuer_tax_id)
		except Exception:
			pass
	issue_dt = _parse_datetime(get('dhEmi') or get('dEmi'))
	auth_dt = _parse_datetime(get('dhRecbto'))
	total = _safe_decimal(get('vNF'))

	return NFeDocumentSummary(
		nsu=nsu,
		schema=schema,
		document_type=tag,
		access_key=access_key,
		issuer_tax_id=issuer_tax_id,
		issuer_name=issuer_name,
		issue_datetime=issue_dt,
		authorization_datetime=auth_dt,
		total_value=total,
		raw_xml=ET.tostring(element, encoding='unicode'),
	)


def _parse_response(content: bytes) -> NFeDistributionResult:
	try:
		root = ET.fromstring(content)
	except ET.ParseError as exc:
		raise NFeDistributionError('Resposta inválida da SEFAZ (não é XML).') from exc

	ns = {
		'soap': _SOAP_NAMESPACE,
		'ws': _WSDL_NAMESPACE,
		'nfe': _NFE_NAMESPACE,
	}
	body = root.find('soap:Body', ns)
	if body is None:
		raise NFeDistributionError('Resposta da SEFAZ não possui body.')

	response_node = body.find('ws:nfeDistDFeInteresseResponse', ns)
	if response_node is None:
		raise NFeDistributionError('Resposta inesperada da SEFAZ.')

	result_node = response_node.find('ws:nfeDistDFeInteresseResult', ns)
	if result_node is None:
		raise NFeDistributionError('Resultado não encontrado na resposta da SEFAZ.')

	ret_node = result_node.find('nfe:retDistDFeInt', ns)
	if ret_node is None:
		raise NFeDistributionError('retDistDFeInt ausente na resposta da SEFAZ.')

	cstat = ret_node.findtext('nfe:cStat', default='', namespaces=ns)
	xmotivo = ret_node.findtext('nfe:xMotivo', default='', namespaces=ns)
	ult_nsu = ret_node.findtext('nfe:ultNSU', default='000000000000000', namespaces=ns)
	max_nsu = ret_node.findtext('nfe:maxNSU', default='000000000000000', namespaces=ns)

	documents: List[NFeDocumentSummary] = []
	for doczip in ret_node.findall('.//nfe:loteDistDFeInt/nfe:docZip', ns):
		nsu = doczip.attrib.get('NSU', '')
		schema = doczip.attrib.get('schema', '')
		try:
			parsed = _decompress_doczip(doczip.text or '')
		except Exception:  # pragma: no cover - defensive logging
			logger.exception('Falha ao descompactar docZip NSU=%s schema=%s', nsu, schema)
			continue
		try:
			documents.append(_parse_document(parsed, nsu, schema))
		except Exception:  # pragma: no cover - defensive
			logger.exception('Erro ao interpretar docZip NSU=%s schema=%s', nsu, schema)
			continue

	return NFeDistributionResult(
		status_code=cstat or '',
		status_message=xmotivo or '',
		last_nsu=ult_nsu or '000000000000000',
		max_nsu=max_nsu or '000000000000000',
		documents=documents,
	)


def consult_nfe_distribution(
	config: SefazConfiguration,
	cnpj: str,
	state_code: str,
	last_nsu: Optional[str] = None,
	nsu: Optional[str] = None,
	access_key: Optional[str] = None,
) -> NFeDistributionResult:
	bundle = _load_certificate(config)
	endpoints = _get_endpoints(config)
	payload = _build_distdfe_payload(
		cnpj,
		config.environment,
		state_code=state_code,
		last_nsu=last_nsu,
		nsu=nsu,
		access_key=access_key,
	)
	timeout = config.timeout or getattr(settings, 'SEFAZ_API_TIMEOUT', 30)

	headers = {
		'Content-Type': 'application/soap+xml; charset=utf-8',
		'SOAPAction': 'http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe/nfeDistDFeInteresse',
		'Accept': 'application/soap+xml',
	}
	last_error: Optional[NFeDistributionError] = None
	with temporary_certificate_files(bundle) as (cert_path, key_path):
		for endpoint in endpoints:
			try:
				response = requests.post(
					endpoint,
					data=payload.encode('utf-8'),
					headers=headers,
					timeout=timeout,
					cert=(cert_path, key_path),
				)
			except requests.RequestException as exc:
				logger.warning('Erro ao consultar SEFAZ em %s: %s', endpoint, exc, exc_info=True)
				last_error = NFeDistributionError('Falha de conexão com a SEFAZ.')
				continue

			if response.status_code != 200:
				logger.warning(
					'SEFAZ respondeu HTTP %s para endpoint %s',
					response.status_code,
					endpoint,
				)
				last_error = NFeDistributionError(f'Erro HTTP {response.status_code} ao consultar a SEFAZ ({endpoint}).')
				continue

			try:
				return _parse_response(response.content)
			except NFeDistributionError as exc:
				logger.warning('Falha ao interpretar resposta da SEFAZ em %s: %s', endpoint, exc, exc_info=True)
				last_error = exc
				continue

	if last_error:
		raise last_error
	raise NFeDistributionError('Não foi possível consultar a SEFAZ em nenhum endpoint configurado.')


__all__ = [
	'NFeDistributionError',
	'NFeCertificateError',
	'NFeDocumentSummary',
	'NFeDistributionResult',
	'consult_nfe_distribution',
]
