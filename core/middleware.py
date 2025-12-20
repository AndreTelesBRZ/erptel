from __future__ import annotations

from typing import Any, Callable

from django.utils.functional import cached_property

from companies.models import Company


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
