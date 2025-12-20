from django.conf import settings
from rest_framework import permissions


class HasAppToken(permissions.BasePermission):
    """
    Valida o header X-App-Token com o token configurado em APP_INTEGRATION_TOKEN.
    Se APP_INTEGRATION_TOKEN não estiver configurado, libera (útil em desenvolvimento).
    """

    def has_permission(self, request, view):
        expected_token = getattr(settings, "APP_INTEGRATION_TOKEN", None)
        if not expected_token:
            return True
        received_token = request.headers.get("X-App-Token")
        return received_token == expected_token
