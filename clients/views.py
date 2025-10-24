from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from .models import Client
from .forms import ClientForm
from django.contrib.auth.decorators import login_required


def index(request):
	clients = Client.objects.all().order_by('-created_at')
	return render(request, 'clients/index.html', {'clients': clients})


def detail(request, pk):
	client = get_object_or_404(Client, pk=pk)
	return render(request, 'clients/detail.html', {'client': client})


@login_required
def create(request):
	if request.method == 'POST':
		form = ClientForm(request.POST)
		if form.is_valid():
			form.save()
			return redirect(reverse('clients:index'))
	else:
		form = ClientForm()
	return render(request, 'clients/form.html', {'form': form})


@login_required
def update(request, pk):
	client = get_object_or_404(Client, pk=pk)
	if request.method == 'POST':
		form = ClientForm(request.POST, instance=client)
		if form.is_valid():
			form.save()
			return redirect(reverse('clients:detail', args=[client.pk]))
	else:
		form = ClientForm(instance=client)
	return render(request, 'clients/form.html', {'form': form, 'client': client})


@login_required
def delete(request, pk):
	client = get_object_or_404(Client, pk=pk)
	if request.method == 'POST':
		client.delete()
		return redirect(reverse('clients:index'))
	return render(request, 'clients/confirm_delete.html', {'client': client})


def report(request):
	total = Client.objects.count()
	return render(request, 'clients/report.html', {'total': total})


@login_required
def export_csv(request):
	import csv
	from django.http import HttpResponse

	response = HttpResponse(content_type='text/csv')
	response['Content-Disposition'] = 'attachment; filename="clients.csv"'
	writer = csv.writer(response)
	writer.writerow(['id', 'first_name', 'last_name', 'email', 'phone', 'created_at'])
	for c in Client.objects.all():
		writer.writerow([c.id, c.first_name, c.last_name, c.email, c.phone, c.created_at])
	return response

# Create your views here.
