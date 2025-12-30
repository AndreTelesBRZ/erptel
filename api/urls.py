# api/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
	ProdutoSyncViewSet,
	ClienteSyncViewSet,
	SefazConfigurationAPIView,
	CompanyNFeAPIView,
	PlanoPagamentoClienteAPIView,
	PlanoPagamentoClienteSyncAPIView,
	LojaViewSet,
	LojaSyncAPIView,
	ReceberPedidoView,
	PedidoViewSet,
	PedidoStatusUpdateView,
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
	path("planos-pagamento-cliente/", PlanoPagamentoClienteAPIView.as_view(), name="api-plano-pagamento-cliente"),
	path("planos-pagamento-cliente/<str:cliente_codigo>/", PlanoPagamentoClienteAPIView.as_view(), name="api-plano-pagamento-cliente-path"),
	path("planos-pagamento-clientes/sync/", PlanoPagamentoClienteSyncAPIView.as_view(), name="api-plano-pagamento-cliente-sync"),
	path("lojas/sync/", LojaSyncAPIView.as_view(), name="api-lojas-sync"),
	path("", include(router.urls)),
	path("pedidos", ReceberPedidoView.as_view(), name="api-pedidos"),
	path("pedidos/<int:pk>/status", PedidoStatusUpdateView.as_view(), name="api-pedido-status"),
	path("login/", CustomAuthToken.as_view(), name="api-login-slash"),
	path("login", CustomAuthToken.as_view(), name="api-login"),
]
