from django.shortcuts import render
from django.db.models import Sum
from django.contrib.auth.decorators import login_required

from .models import PurchaseOrder


@login_required
def index(request):
    status_filter = request.GET.get('status', '').strip()
    qs = PurchaseOrder.objects.all()
    company = getattr(request, 'company', None)
    if company:
        qs = qs.filter(company=company)
    if status_filter:
        qs = qs.filter(status=status_filter)

    totals = qs.aggregate(total=Sum('total_amount'))

    context = {
        'orders': qs,
        'status_filter': status_filter,
        'status_choices': PurchaseOrder.STATUS_CHOICES,
        'total_amount': totals['total'] or 0,
        'active_company': company,
    }
    return render(request, 'purchases/index.html', context)

# Create your views here.
