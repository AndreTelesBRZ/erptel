"""Utility helpers for CPF/CNPJ normalization and formatting."""

from __future__ import annotations

import re
from typing import Optional

DIGITS_RE = re.compile(r'\D+')


def only_digits(value: Optional[str]) -> str:
	if value is None:
		return ''
	return DIGITS_RE.sub('', str(value))


def normalize_cpf(value: Optional[str]) -> str:
	digits = only_digits(value)
	if len(digits) != 11:
		raise ValueError('CPF deve conter 11 dígitos.')
	return digits


def normalize_cnpj(value: Optional[str]) -> str:
	digits = only_digits(value)
	if len(digits) != 14:
		raise ValueError('CNPJ deve conter 14 dígitos.')
	return digits


def format_cpf(value: Optional[str]) -> str:
	digits = only_digits(value)
	if len(digits) != 11:
		return digits
	return f'{digits[0:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:11]}'


def format_cnpj(value: Optional[str]) -> str:
	digits = only_digits(value)
	if len(digits) != 14:
		return digits
	return '{}.{}.{}/{}-{}'.format(
		digits[0:2],
		digits[2:5],
		digits[5:8],
		digits[8:12],
		digits[12:14],
	)


__all__ = [
	'only_digits',
	'normalize_cpf',
	'normalize_cnpj',
	'format_cpf',
	'format_cnpj',
]
