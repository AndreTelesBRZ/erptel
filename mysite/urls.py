"""
URL configuration for mysite project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from core import views as core_views
from rest_framework.authtoken import views as drf_authtoken_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', core_views.logout_view, name='logout'),
    path('accounts/logout/', core_views.logout_view, name='accounts_logout'),
    path('dashboard/', core_views.dashboard, name='dashboard'),
    path('products/', include('products.urls')),
    path('clients/', include('clients.urls')),
    path('sales/', include('sales.urls')),
    path('purchases/', include('purchases.urls')),
    path('finance/', include('finance.urls')),
    path('custos/', include('custos.urls')),
    path('companies/', include('companies.urls')),
    path('relatorios/', include('relatorios.urls')),
    path('estoque/', include('estoque.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('core/', include('core.urls')),
    path('api/', include('api.urls')),
    path('api-token-auth/', drf_authtoken_views.obtain_auth_token, name='api-token-auth'),
    path('api-auth/', include('rest_framework.urls')),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
