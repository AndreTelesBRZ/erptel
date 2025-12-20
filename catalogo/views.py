from django.views.generic import ListView
from api.models import Produto

class ProdutoListView(ListView):
    model = Produto
    template_name = "catalogo/produto_list.html"
    paginate_by = 50

    def get_queryset(self):
        qs = Produto.objects.all().order_by("codigo")
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(descricao__icontains=q) | qs.filter(codigo__icontains=q) | qs.filter(ean__icontains=q)
        return qs
