from __future__ import annotations

from typing import Any, Callable

from django.utils.functional import cached_property

from companies.models import Company
from api.models import Loja
from .lojas_sync import sync_lojas_from_api
from .utils.loja import find_loja_by_codigo, normalize_loja_codigo


class ActiveCompanyMiddleware:
    """
    Attach the active company to each request using the session and user permissions.
    """

    session_key = 'active_company_id'

    def __init__(self, get_response: Callable[[Any], Any]) -> None:
        self.get_response = get_response

    def __call__(self, request):
        request.available_companies = []
        request.company = None

        if request.user.is_authenticated:
            profile = getattr(request.user, 'access_profile', None)
            if profile and profile.can_view_all_companies:
                base_qs = Company.objects.filter(is_active=True)
            else:
                base_qs = Company.objects.filter(is_active=True)
                if profile and profile.companies.exists():
                    base_qs = base_qs.filter(pk__in=profile.companies.values_list('pk', flat=True))
            request.available_companies = list(base_qs.order_by('trade_name', 'name'))

            company_id = request.session.get(self.session_key)
            company = next((c for c in request.available_companies if c.pk == company_id), None)
            if not company and request.available_companies:
                company = request.available_companies[0]
                request.session[self.session_key] = company.pk
            request.company = company

        response = self.get_response(request)
        return response


class ActiveLojaMiddleware:
    """
    Attach the active store (loja) to each request using the session.
    """

    session_key = "active_loja_codigo"

    def __init__(self, get_response: Callable[[Any], Any]) -> None:
        self.get_response = get_response

    def __call__(self, request):
        request.available_lojas = []
        request.loja = None
        request.loja_codigo = None

        if request.user.is_authenticated:
            if not Loja.objects.exists():
                try:
                    sync_lojas_from_api()
                except Exception:
                    pass
            request.available_lojas = list(Loja.objects.all().order_by("codigo"))
            loja_codigo = request.session.get(self.session_key)
            loja, normalized_codigo = find_loja_by_codigo(request.available_lojas, loja_codigo)
            if not loja and request.available_lojas:
                loja = request.available_lojas[0]
                normalized_codigo = normalize_loja_codigo(loja.codigo, [l.codigo for l in request.available_lojas])
                request.session[self.session_key] = normalized_codigo or loja.codigo
            request.loja = loja
            request.loja_codigo = normalized_codigo or (loja.codigo if loja else loja_codigo)

        response = self.get_response(request)
        return response
