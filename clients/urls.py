from django.urls import path
from . import views

app_name = 'clients'

urlpatterns = [
    path('', views.index, name='index'),
    path('sync/', views.sync_list, name='sync_list'),
    path('report/', views.report, name='report'),
    path('report/csv/', views.export_csv, name='report_csv'),
    path('report/pdf/', views.export_pdf, name='report_pdf'),
    path('sefaz/lookup/', views.client_sefaz_lookup, name='sefaz_lookup'),
    path('<int:pk>/', views.detail, name='detail'),
]
