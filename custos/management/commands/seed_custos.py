from django.core.management.base import BaseCommand

from custos.models import CostParameter

DEFAULT_PARAMETERS = [
	{
		'key': 'despesa_variavel_percent',
		'label': 'Despesas variáveis (%)',
		'value': 5,
		'unit': '%',
		'is_percentage': True,
		'description': 'Percentual médio de despesas variáveis utilizado em precificações.',
	},
	{
		'key': 'despesa_fixa_percent',
		'label': 'Despesas fixas (%)',
		'value': 8,
		'unit': '%',
		'is_percentage': True,
		'description': 'Percentual médio de despesas fixas.',
	},
	{
		'key': 'tributos_percent',
		'label': 'Tributos (%)',
		'value': 12,
		'unit': '%',
		'is_percentage': True,
		'description': 'Carga tributária padrão utilizada nas simulações.',
	},
	{
		'key': 'margem_desejada_percent',
		'label': 'Margem desejada (%)',
		'value': 30,
		'unit': '%',
		'is_percentage': True,
		'description': 'Margem alvo para precificação de produtos.',
	},
]


class Command(BaseCommand):
	help = 'Cria parâmetros globais padrão para o módulo de custos.'

	def add_arguments(self, parser):
		parser.add_argument(
			'--force',
			action='store_true',
			help='Atualiza valores existentes com os padrões informados.',
		)

	def handle(self, *args, **options):
		force = options['force']
		created = 0
		updated = 0

		for data in DEFAULT_PARAMETERS:
			obj, created_flag = CostParameter.objects.get_or_create(
				key=data['key'],
				defaults=data,
			)
			if created_flag:
				created += 1
				self.stdout.write(self.style.SUCCESS(f'Criado: {obj.label}'))
			elif force:
				for field, value in data.items():
					setattr(obj, field, value)
				obj.save()
				updated += 1
				self.stdout.write(self.style.WARNING(f'Atualizado: {obj.label}'))
			else:
				self.stdout.write(f'Existente (sem alterações): {obj.label}')

		summary = f'Parâmetros criados: {created}; atualizados: {updated}; total configurado: {CostParameter.objects.count()}'
		self.stdout.write(self.style.SUCCESS(summary))
