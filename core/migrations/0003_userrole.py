from django.db import migrations, models


def seed_user_roles(apps, schema_editor):
	UserRole = apps.get_model('core', 'UserRole')
	default_roles = [
		('seller', 'Vendedor', 'Responsável por vendas e atendimento comercial.'),
		('cashier', 'Caixa', 'Opera o caixa e finaliza pedidos.'),
		('inventory', 'Estoque', 'Controla movimentações de estoque.'),
		('administration', 'Administração', 'Gerencia configurações gerais do sistema.'),
		('finance', 'Financeiro', 'Acompanha contas a pagar/receber e relatórios financeiros.'),
		('purchasing', 'Compras', 'Realiza pedidos e negociações com fornecedores.'),
	]
	for code, name, description in default_roles:
		UserRole.objects.get_or_create(code=code, defaults={'name': name, 'description': description})


def remove_seeded_roles(apps, schema_editor):
	UserRole = apps.get_model('core', 'UserRole')
	UserRole.objects.filter(code__in=[
		'seller', 'cashier', 'inventory', 'administration', 'finance', 'purchasing',
	]).delete()


class Migration(migrations.Migration):

	dependencies = [
		('core', '0002_useraccessprofile'),
	]

	operations = [
		migrations.CreateModel(
			name='UserRole',
			fields=[
				('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
				('code', models.SlugField(unique=True, verbose_name='Código')),
				('name', models.CharField(max_length=120, unique=True, verbose_name='Nome da função')),
				('description', models.CharField(blank=True, max_length=255, verbose_name='Descrição')),
				('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
			],
			options={
				'verbose_name': 'Função de usuário',
				'verbose_name_plural': 'Funções de usuário',
				'ordering': ('name',),
			},
		),
		migrations.AddField(
			model_name='useraccessprofile',
			name='roles',
			field=models.ManyToManyField(blank=True, related_name='profiles', to='core.userrole', verbose_name='Funções atribuídas'),
		),
		migrations.RunPython(seed_user_roles, remove_seeded_roles),
	]
