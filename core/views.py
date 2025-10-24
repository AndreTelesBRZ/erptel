from django.shortcuts import render
from products.models import Product
from clients.models import Client
from django.contrib.auth.decorators import login_required


@login_required
def dashboard(request):
	total_products = Product.objects.count()
	total_clients = Client.objects.count()
	recent_products = Product.objects.order_by('-created_at')[:5]
	recent_clients = Client.objects.order_by('-created_at')[:5]
	return render(request, 'core/dashboard.html', {
		'total_products': total_products,
		'total_clients': total_clients,
		'recent_products': recent_products,
		'recent_clients': recent_clients,
	})

# Create your views here.


def home(request):
	# compatibility: redirect to dashboard if authenticated, otherwise to login
	from django.shortcuts import redirect
	if request.user.is_authenticated:
		return redirect('dashboard')
	return redirect('login')
