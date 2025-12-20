from django.urls import path

from . import views

app_name = "estoque"

urlpatterns = [
    path("", views.inventory_list, name="inventory_list"),
    path("selecionar/", views.inventory_from_selection, name="inventory_from_selection"),
    path("novo/", views.inventory_create, name="inventory_create"),
    path("coletor/", views.inventory_collector, name="inventory_collector"),
    path("coletor/exportar/", views.inventory_collector_export, name="inventory_collector_export"),
    path("<int:pk>/", views.inventory_detail, name="inventory_detail"),
    path("<int:pk>/exportar/", views.inventory_export_csv, name="inventory_export"),
    path("<int:pk>/importar/", views.inventory_import, name="inventory_import"),
    path("<int:pk>/iniciar/", views.inventory_start, name="inventory_start"),
    path("<int:pk>/fechar/", views.inventory_close, name="inventory_close"),
]
