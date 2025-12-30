from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('lookups/<slug:slug>/', views.lookup_records, name='lookup'),
    path('settings/profile/', views.profile_settings, name='settings_profile'),
    path('settings/email/', views.email_settings, name='settings_email'),
    path('settings/sales/', views.sales_settings, name='settings_sales'),
    path('settings/sefaz/', views.sefaz_settings, name='settings_sefaz'),
    path('settings/access/', views.access_settings_list, name='settings_access'),
    path('settings/access/new/', views.access_settings_create, name='settings_access_create'),
    path('settings/access/<int:user_id>/', views.access_settings_edit, name='settings_access_edit'),
    path('settings/api-tokens/', views.api_user_tokens, name='settings_api_tokens'),
    path('settings/api-tokens/<int:user_id>/', views.api_user_edit, name='settings_api_tokens_edit'),
    path('company/switch/', views.switch_company, name='switch_company'),
    path('loja/switch/', views.switch_loja, name='switch_loja'),
]
