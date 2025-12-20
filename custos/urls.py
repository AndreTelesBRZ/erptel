from django.urls import path

from . import views

app_name = 'custos'

urlpatterns = [
path('', views.parameter_list, name='parameter_list'),
path('parametros/novo/', views.parameter_create, name='parameter_create'),
path('parametros/<int:pk>/editar/', views.parameter_edit, name='parameter_edit'),
path('compra/', views.purchase_costs, name='purchase_costs'),
path('lotes/', views.batch_list, name='batch_list'),
path('lotes/novo/', views.batch_create, name='batch_create'),
path('lotes/<int:pk>/', views.batch_detail, name='batch_detail'),
path('lotes/<int:pk>/selecionar/', views.batch_select_items, name='batch_select_items'),
]
