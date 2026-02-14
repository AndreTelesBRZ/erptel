# api/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
	ProdutoSyncViewSet,
	ClienteSyncViewSet,
	SefazConfigurationAPIView,
	CompanyNFeAPIView,
	LojaViewSet,
	LojaSyncAPIView,
	ReceberPedidoView,
	PedidoDetailAPIView,
	PedidoViewSet,
	CustomAuthToken,
)
router = DefaultRouter()
router.register(r"produtos-sync", ProdutoSyncViewSet, basename="produtos-sync")
router.register(r"clientes", ClienteSyncViewSet, basename="clientes")
router.register(r"lojas", LojaViewSet, basename="lojas")
router.register(r"pedidos-venda", PedidoViewSet, basename="pedidos-venda")
urlpatterns = [
	path("sefaz/config/", SefazConfigurationAPIView.as_view(), name="api-sefaz-config"),
	path("companies/<int:pk>/nfe/", CompanyNFeAPIView.as_view(), name="api-company-nfe"),
	path("lojas/sync/", LojaSyncAPIView.as_view(), name="api-lojas-sync"),
	path("pedidos/<int:pk>", PedidoDetailAPIView.as_view(), name="api-pedidos-detail"),
	path("", include(router.urls)),
	path("pedidos", ReceberPedidoView.as_view(), name="api-pedidos"),
	path("login/", CustomAuthToken.as_view(), name="api-login-slash"),
	path("login", CustomAuthToken.as_view(), name="api-login"),
]
