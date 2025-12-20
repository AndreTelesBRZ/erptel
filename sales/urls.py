from django.urls import path

from . import views

app_name = 'sales'

urlpatterns = [
	path('quotes/', views.quote_list, name='quote_list'),
	path('quotes/new/', views.quote_create, name='quote_create'),
	path('quotes/product-lookup/', views.quote_product_lookup, name='quote_product_lookup'),
	path('quotes/<int:pk>/pdf/', views.quote_pdf, name='quote_pdf'),
	path('quotes/<int:pk>/', views.quote_detail, name='quote_detail'),
	path('quotes/<int:pk>/edit/', views.quote_edit, name='quote_edit'),
	path('quotes/<int:pk>/convert/', views.quote_convert_to_order, name='quote_convert'),
	path('orders/', views.order_list, name='order_list'),
	path('orders/<int:pk>/', views.order_detail, name='order_detail'),
	path('api-orders/', views.api_order_list, name='api_order_list'),
	path('api-orders/<int:pk>/', views.api_order_detail, name='api_order_detail'),
	path('sellers/', views.seller_list, name='seller_list'),
	path('sellers/<int:pk>/', views.seller_list, name='seller_edit'),
	path('sellers/<int:pk>/delete/', views.seller_delete, name='seller_delete'),
]
