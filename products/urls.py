from django.urls import path
from . import views

app_name = 'products'

urlpatterns = [
    path('', views.index, name='index'),
    path('sync/', views.sync_list, name='sync_list'),
    path('sync/apply/', views.sync_apply, name='sync_apply'),
    path('import/', views.import_upload, name='import_upload'),
    path('import/preview/', views.import_preview, name='import_preview'),
    path('import/errors/<str:key>.csv', views.import_errors_csv, name='import_errors_csv'),
    path('import/status/<str:key>/', views.import_status, name='import_status'),
    path('import/progress/<str:key>/', views.import_progress, name='import_progress'),
    path('report/', views.report, name='report'),
    path('export/csv/', views.export_products_csv, name='export_csv'),
    path('report/csv/', views.export_products_csv, name='report_csv'),
    path('report/pdf/', views.export_products_pdf, name='report_pdf'),
    path('price-adjustments/new/', views.price_adjustment_prepare, name='price_adjustment_prepare'),
    path('price-adjustments/history/', views.price_adjustment_history, name='price_adjustment_history'),
    path('price-adjustments/<int:pk>/', views.price_adjustment_detail, name='price_adjustment_detail'),
    # CRUD desabilitado (somente leitura)
    path('groups/', views.group_list, name='group_list'),
    path('groups/<int:pk>/', views.group_list, name='group_edit'),
    path('groups/<int:pk>/delete/', views.group_delete, name='group_delete'),
    path('subgroups/', views.subgroup_list, name='subgroup_list'),
    path('subgroups/<int:pk>/', views.subgroup_list, name='subgroup_edit'),
    path('subgroups/<int:pk>/delete/', views.subgroup_delete, name='subgroup_delete'),
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/sefaz/lookup/', views.supplier_sefaz_lookup, name='supplier_sefaz_lookup'),
    path('suppliers/<int:pk>/', views.supplier_list, name='supplier_edit'),
    path('suppliers/<int:pk>/delete/', views.supplier_delete, name='supplier_delete'),
    path('suppliers/catalog/from-selection/', views.supplier_catalog_from_selection, name='supplier_catalog_from_selection'),
    path('suppliers/<int:supplier_id>/catalog/', views.supplier_catalog, name='supplier_catalog'),
    path('suppliers/<int:supplier_id>/catalog/select/', views.supplier_catalog_select, name='supplier_catalog_select'),
    path('suppliers/<int:supplier_id>/catalog/export/', views.supplier_catalog_export, name='supplier_catalog_export'),
    path('suppliers/<int:supplier_id>/catalog/<int:item_id>/edit/', views.supplier_catalog_edit, name='supplier_catalog_edit'),
    path('suppliers/<int:supplier_id>/catalog/<int:item_id>/delete/', views.supplier_catalog_delete, name='supplier_catalog_delete'),
    path('<int:pk>/', views.detail, name='detail'),
]
