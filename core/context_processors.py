from api.models import Loja
from .middleware import ActiveLojaMiddleware
from .lojas_sync import sync_lojas_from_api
from .utils.loja import find_loja_by_codigo
from .models import UserAccessProfile


def active_company(request):
    return {
        'active_company': getattr(request, 'company', None),
        'available_companies': getattr(request, 'available_companies', []),
    }


def active_loja(request):
    if not hasattr(request, 'available_lojas') and getattr(request, 'user', None) and request.user.is_authenticated:
        if not Loja.objects.exists():
            try:
                sync_lojas_from_api()
            except Exception:
                pass
        available_lojas = list(Loja.objects.all().order_by("codigo"))
        loja_codigo = request.session.get(ActiveLojaMiddleware.session_key)
        loja, normalized_codigo = find_loja_by_codigo(available_lojas, loja_codigo)
        if not loja and available_lojas:
            loja = available_lojas[0]
            normalized_codigo = loja.codigo
            request.session[ActiveLojaMiddleware.session_key] = normalized_codigo
        request.available_lojas = available_lojas
        request.loja = loja
        request.loja_codigo = normalized_codigo or (loja.codigo if loja else None)
    if not getattr(request, 'loja_codigo', None):
        session_codigo = request.session.get(ActiveLojaMiddleware.session_key)
        if session_codigo:
            request.loja_codigo = session_codigo
    return {
        'active_loja': getattr(request, 'loja', None),
        'available_lojas': getattr(request, 'available_lojas', []),
    }


def user_profile(request):
    user = getattr(request, 'user', None)
    profile = None
    if user and user.is_authenticated:
        cached = getattr(user, '_cached_access_profile', None)
        if cached is not None:
            profile = cached
        else:
            try:
                profile = user.access_profile
            except UserAccessProfile.DoesNotExist:
                profile = None
            setattr(user, '_cached_access_profile', profile)
    return {'user_profile': profile}
