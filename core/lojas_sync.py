from __future__ import annotations

from typing import Iterable

import requests
from django.conf import settings
from django.utils import timezone

from api.models import Loja


def _coerce_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_loja_payload(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get("data") or payload.get("items") or payload.get("results") or payload
    if not isinstance(payload, list):
        return []

    normalized: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        codigo = _coerce_str(item.get("codigo") or item.get("code") or item.get("loja_codigo"))
        if not codigo:
            continue
        normalized.append(
            {
                "codigo": codigo,
                "razao_social": _coerce_str(item.get("razao_social") or item.get("razaoSocial")),
                "nome_fantasia": _coerce_str(item.get("nome_fantasia") or item.get("nomeFantasia")),
                "cnpj_cpf": _coerce_str(item.get("cnpj_cpf") or item.get("cnpjCpf")),
                "ie_rg": _coerce_str(item.get("ie_rg") or item.get("ieRg")),
                "tipo_pf_pj": _coerce_str(item.get("tipo_pf_pj") or item.get("tipoPfPj")),
                "telefone1": _coerce_str(item.get("telefone1") or item.get("telefone_1")),
                "telefone2": _coerce_str(item.get("telefone2") or item.get("telefone_2")),
                "endereco": _coerce_str(item.get("endereco")),
                "bairro": _coerce_str(item.get("bairro")),
                "numero": _coerce_str(item.get("numero")),
                "complemento": _coerce_str(item.get("complemento")),
                "cep": _coerce_str(item.get("cep")),
                "email": _coerce_str(item.get("email")),
                "cidade": _coerce_str(item.get("cidade")),
                "estado": _coerce_str(item.get("estado")),
            }
        )
    return normalized


def _build_lojas_url() -> str:
    base_url = getattr(settings, "LOJAS_API_BASE_URL", "").rstrip("/")
    if not base_url:
        return ""
    path = getattr(settings, "LOJAS_API_PATH", "/api/lojas")
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base_url}{path}"


def _build_headers() -> dict[str, str]:
    token = getattr(settings, "LOJAS_API_TOKEN", "") or getattr(settings, "APP_INTEGRATION_TOKEN", "")
    if not token:
        return {}
    header_name = getattr(settings, "LOJAS_API_AUTH_HEADER", "Authorization")
    if header_name.lower() == "authorization" and not token.lower().startswith("bearer "):
        token = f"Bearer {token}"
    return {header_name: token}


def fetch_lojas_from_api() -> list[dict]:
    url = _build_lojas_url()
    if not url:
        return []
    timeout = getattr(settings, "LOJAS_API_TIMEOUT", 10)
    response = requests.get(url, headers=_build_headers(), timeout=timeout)
    response.raise_for_status()
    return _normalize_loja_payload(response.json())


def sync_lojas_from_api() -> int:
    payload = fetch_lojas_from_api()
    if not payload:
        return 0
    now = timezone.now()
    lojas = [Loja(updated_at=now, **item) for item in payload]
    Loja.objects.bulk_create(
        lojas,
        update_conflicts=True,
        unique_fields=["codigo"],
        update_fields=[
            "razao_social",
            "nome_fantasia",
            "cnpj_cpf",
            "ie_rg",
            "tipo_pf_pj",
            "telefone1",
            "telefone2",
            "endereco",
            "bairro",
            "numero",
            "complemento",
            "cep",
            "email",
            "cidade",
            "estado",
            "updated_at",
        ],
    )
    return len(lojas)
