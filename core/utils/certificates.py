from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
import os
from pathlib import Path
import tempfile
from typing import Generator, Optional, Tuple

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from django.utils import timezone


class CertificateError(Exception):
	"""Raised when the digital certificate cannot be loaded or is invalid."""


@dataclass(slots=True)
class CertificateMetadata:
	subject: str
	serial_number: str
	valid_from: timezone.datetime
	valid_until: timezone.datetime


@dataclass(slots=True)
class CertificateBundle:
	certificate_pem: bytes
	private_key_pem: bytes
	chain_pem: bytes
	metadata: CertificateMetadata

def _to_timezone_aware(dt: datetime) -> datetime:
	if not isinstance(dt, datetime):
		raise CertificateError('Formato de data inválido no certificado.')
	if timezone.is_naive(dt):
		return timezone.make_aware(dt, timezone=dt_timezone.utc)
	return dt


def _format_subject(cert: x509.Certificate) -> str:
	try:
		return cert.subject.rfc4514_string()
	except Exception:
		# Fallback concatenating components if rfc4514_string fails
		parts = []
		for name in cert.subject:
			for attribute in name:
				parts.append(f"{attribute.oid._name}={attribute.value}")
		return ', '.join(parts)


def load_pkcs12_from_bytes(data: bytes, password: Optional[str]) -> CertificateBundle:
	if not data:
		raise CertificateError('O arquivo do certificado está vazio.')
	try:
		private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
			data,
			password.encode('utf-8') if password else None,
		)
	except ValueError as exc:
		raise CertificateError('Não foi possível carregar o certificado. Verifique a senha informada.') from exc
	except Exception as exc:  # pragma: no cover - defensive
		raise CertificateError('Erro desconhecido ao carregar o certificado digital.') from exc

	if certificate is None or private_key is None:
		raise CertificateError('O arquivo não contém um certificado e chave privada válidos.')

	cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
	private_key_pem = private_key.private_bytes(
		encoding=serialization.Encoding.PEM,
		format=serialization.PrivateFormat.PKCS8,
		encryption_algorithm=serialization.NoEncryption(),
	)
	chain_pem = cert_pem
	if additional_certs:
		for extra in additional_certs:
			if not isinstance(extra, x509.Certificate):
				continue
			chain_pem += extra.public_bytes(serialization.Encoding.PEM)

	metadata = CertificateMetadata(
		subject=_format_subject(certificate),
		serial_number=f"{certificate.serial_number:X}",
		valid_from=_to_timezone_aware(certificate.not_valid_before),
		valid_until=_to_timezone_aware(certificate.not_valid_after),
	)
	return CertificateBundle(
		certificate_pem=cert_pem,
		private_key_pem=private_key_pem,
		chain_pem=chain_pem,
		metadata=metadata,
	)


def load_pkcs12_from_path(path: Path | str, password: Optional[str]) -> CertificateBundle:
	try:
		data = Path(path).read_bytes()
	except FileNotFoundError as exc:
		raise CertificateError('Arquivo do certificado não encontrado.') from exc
	return load_pkcs12_from_bytes(data, password)


@contextmanager
def temporary_certificate_files(bundle: CertificateBundle) -> Generator[Tuple[str, str], None, None]:
	cert_fd = tempfile.NamedTemporaryFile('wb', delete=False)
	key_fd = tempfile.NamedTemporaryFile('wb', delete=False)
	try:
		cert_fd.write(bundle.chain_pem or bundle.certificate_pem)
		cert_fd.flush()
		key_fd.write(bundle.private_key_pem)
		key_fd.flush()
		cert_fd.close()
		key_fd.close()
		yield cert_fd.name, key_fd.name
	finally:
		for path in (getattr(cert_fd, 'name', None), getattr(key_fd, 'name', None)):
			if path:
				try:
					os.unlink(path)
				except FileNotFoundError:
					pass
				except PermissionError:
					pass


__all__ = [
	'CertificateError',
	'CertificateMetadata',
	'CertificateBundle',
	'load_pkcs12_from_bytes',
	'load_pkcs12_from_path',
	'temporary_certificate_files',
]
