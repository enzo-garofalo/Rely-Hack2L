from django.conf import settings
from rest_framework.permissions import BasePermission


class HasErpApiKey(BasePermission):
    """Autenticação simples do ERP simulado: header X-API-Key (RF33, RNF04)."""

    message = "API key inválida ou ausente."

    def has_permission(self, request, view):
        api_key = request.headers.get("X-API-Key")
        return bool(api_key) and api_key == settings.ERP_API_KEY
