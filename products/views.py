from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from .models import Product
from .forms import ProductForm
from django.db.models import Avg


def index(request):
	products = Product.objects.all().order_by('-created_at')
	return render(request, 'products/index.html', {'products': products})


def detail(request, pk):
	product = get_object_or_404(Product, pk=pk)
	return render(request, 'products/detail.html', {'product': product})


from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from .forms import ProductImportForm
from .utils import import_products_from_file


@login_required
def create(request):
	if request.method == 'POST':
		form = ProductForm(request.POST)
		if form.is_valid():
			form.save()
			return redirect(reverse('products:index'))
	else:
		form = ProductForm()
	return render(request, 'products/form.html', {'form': form})


@login_required
def update(request, pk):
	product = get_object_or_404(Product, pk=pk)
	if request.method == 'POST':
		form = ProductForm(request.POST, instance=product)
		if form.is_valid():
			form.save()
			return redirect(reverse('products:detail', args=[product.pk]))
	else:
		form = ProductForm(instance=product)
	return render(request, 'products/form.html', {'form': form, 'product': product})


@login_required
def delete(request, pk):
	product = get_object_or_404(Product, pk=pk)
	if request.method == 'POST':
		product.delete()
		return redirect(reverse('products:index'))
	return render(request, 'products/confirm_delete.html', {'product': product})


def report(request):
	total = Product.objects.count()
	avg_price = Product.objects.all().aggregate(Avg('price'))['price__avg']
	return render(request, 'products/report.html', {'total': total, 'avg_price': avg_price})


@login_required
def export_csv(request):
	import csv
	from django.http import HttpResponse

	response = HttpResponse(content_type='text/csv')
	response['Content-Disposition'] = 'attachment; filename="products.csv"'
	writer = csv.writer(response)
	writer.writerow(['id', 'name', 'description', 'price', 'created_at'])
	for p in Product.objects.all():
		writer.writerow([p.id, p.name, p.description, p.price, p.created_at])
	return response



@staff_member_required
def import_upload(request):
	if request.method == 'POST':
		form = ProductImportForm(request.POST, request.FILES)
		if form.is_valid():
			f = form.cleaned_data['csv_file']
			# file-like object
			created, updated, msgs = import_products_from_file(f)
			for m in msgs:
				messages.info(request, m)
			messages.success(request, f'Import finished. Created: {created}, Updated: {updated}')
			return redirect('products:index')
	else:
		form = ProductImportForm()
	return render(request, 'products/import_upload.html', {'form': form})

# Create your views here.
