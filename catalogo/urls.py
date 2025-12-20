from django.urls import path
from .views import ProdutoListView
urlpatterns = [path("produtos/", ProdutoListView.as_view(), name="produtos")]
