from django.conf import settings
from rest_framework import permissions


def _matches_app_token(request, expected_token: str) -> bool:
    received_token = (request.headers.get("X-App-Token") or "").strip()
    if received_token == expected_token:
        return True
    auth_header = (request.headers.get("Authorization") or "").strip()
    if not auth_header:
        return False
    scheme, _, raw_value = auth_header.partition(" ")
    if raw_value:
        return scheme.lower() in ("bearer", "token", "app") and raw_value.strip() == expected_token
    return auth_header == expected_token


class HasAppToken(permissions.BasePermission):
    """
    Valida o header X-App-Token com o token configurado em APP_INTEGRATION_TOKEN.
    Se APP_INTEGRATION_TOKEN não estiver configurado, libera (útil em desenvolvimento).
    """

    def has_permission(self, request, view):
        expected_token = getattr(settings, "APP_INTEGRATION_TOKEN", None)
        if not expected_token:
            return True
        return _matches_app_token(request, expected_token)


class HasAppTokenOrAuthenticated(permissions.BasePermission):
    """
    Permite acesso via usuário autenticado ou via X-App-Token válido.
    """

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            return True
        expected_token = getattr(settings, "APP_INTEGRATION_TOKEN", None)
        if not expected_token:
            return True
        return _matches_app_token(request, expected_token)
