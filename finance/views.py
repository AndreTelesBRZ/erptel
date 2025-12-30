from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum

from .models import FinanceEntry


@login_required
def index(request):
    entry_type = request.GET.get('type', '').strip()
    show_paid = request.GET.get('paid', '').strip()

    qs = FinanceEntry.objects.all()
    loja_codigo = getattr(request, "loja_codigo", None)
    if loja_codigo:
        qs = qs.filter(loja_codigo=loja_codigo)
    if entry_type in ('receivable', 'payable'):
        qs = qs.filter(entry_type=entry_type)
    if show_paid == 'open':
        qs = qs.filter(paid=False)
    elif show_paid == 'closed':
        qs = qs.filter(paid=True)

    totals = qs.aggregate(total=Sum('amount'))
    context = {
        'entries': qs,
        'entry_type': entry_type,
        'status_filter': show_paid,
        'total_amount': totals['total'] or 0,
        'type_choices': FinanceEntry.ENTRY_TYPES,
    }
    return render(request, 'finance/index.html', context)

# Create your views here.
