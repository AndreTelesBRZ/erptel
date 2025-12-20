from django import template
from django.utils.http import urlencode

register = template.Library()


@register.simple_tag(takes_context=True)
def sort_url(context, col, current_sort, current_dir):
    """Build a querystring preserving current filters and toggling sort direction.

    - If the requested column is already the current sort and dir is 'asc',
      toggles to 'desc'. Otherwise uses 'asc'.
    - Resets page to 1.
    Usage: href="{% sort_url 'name' sort dir %}"
    """
    request = context.get('request')
    params = request.GET.copy() if request else {}
    params['sort'] = col
    if current_sort == col and str(current_dir).lower() == 'asc':
        params['dir'] = 'desc'
    else:
        params['dir'] = 'asc'
    params['page'] = '1'
    return '?' + urlencode(params, doseq=True)


@register.simple_tag
def sort_caret(col, current_sort, current_dir):
    """Return ▲ or ▼ when the given column is active; otherwise empty."""
    if col == current_sort:
        return '▲' if str(current_dir).lower() == 'asc' else '▼'
    return ''


@register.simple_tag(takes_context=True)
def qs_url(context, **pairs):
    """Build a querystring preserving current GET params and replacing with given pairs.
    Pass value=None to remove a key. Returns string beginning with '?'.
    """
    request = context.get('request')
    params = request.GET.copy() if request else {}
    for k, v in pairs.items():
        if v is None:
            params.pop(k, None)
        else:
            params[k] = v
    return '?' + urlencode(params, doseq=True)


@register.simple_tag(takes_context=True)
def page_url(context, number):
    """Return URL for a specific page, preserving other filters/sort."""
    try:
        number = int(number)
    except Exception:
        number = 1
    return qs_url(context, page=str(number))


@register.simple_tag(takes_context=True)
def per_page_url(context, per_page):
    """Return URL setting per_page and resetting page to 1."""
    try:
        per_page = int(per_page)
    except Exception:
        per_page = 20
    return qs_url(context, per_page=str(per_page), page='1')
