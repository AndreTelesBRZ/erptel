from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .services import get_report_context


@login_required
def index(request):
    context = {
        "page_title": "Relatórios",
        **get_report_context(company=getattr(request, "company", None)),
    }
    return render(request, "relatorios/index.html", context)
