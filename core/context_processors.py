from .models import UserAccessProfile


def active_company(request):
    return {
        'active_company': getattr(request, 'company', None),
        'available_companies': getattr(request, 'available_companies', []),
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
