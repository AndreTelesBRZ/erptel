from django.urls import path

from . import views

app_name = 'companies'

urlpatterns = [
	path('', views.company_list, name='list'),
	path('new/', views.company_create, name='create'),
	path('<int:pk>/edit/', views.company_edit, name='edit'),
	path('<int:pk>/nfe/', views.company_nfe_list, name='nfe'),
	path('<int:pk>/nfe/json/', views.company_nfe_json, name='nfe_json'),
	path('<int:pk>/delete/', views.company_delete, name='delete'),
	path('sefaz/lookup/', views.company_sefaz_lookup, name='sefaz_lookup'),
]
