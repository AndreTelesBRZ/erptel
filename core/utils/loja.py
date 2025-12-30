from __future__ import annotations

from typing import Iterable, Optional


def normalize_loja_codigo(code: Optional[str], sample_codes: Iterable[str] | None = None) -> str:
    value = (code or "").strip()
    if not value:
        return ""
    if not value.isdigit():
        return value
    target_len = None
    if sample_codes:
        for sample in sample_codes:
            sample_value = (sample or "").strip()
            if sample_value.isdigit():
                if len(sample_value) in (5, 6):
                    target_len = len(sample_value)
                    break
    if target_len in (5, 6):
        return value.zfill(target_len)
    if len(value) < 6:
        return value.zfill(6)
    return value


def find_loja_by_codigo(lojas, codigo: Optional[str]):
    sample_codes = [l.codigo for l in lojas]
    normalized = normalize_loja_codigo(codigo, sample_codes)
    if not normalized:
        return None, normalized
    for loja in lojas:
        if normalize_loja_codigo(loja.codigo, sample_codes) == normalized:
            return loja, normalized
    return None, normalized
