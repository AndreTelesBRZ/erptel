from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .services import get_report_context


@login_required
def index(request):
    loja_codigo = getattr(request, "loja_codigo", None)
    context = {
        "page_title": "Relatórios",
        **get_report_context(company=getattr(request, "company", None), loja_codigo=loja_codigo),
    }
    return render(request, "relatorios/index.html", context)
