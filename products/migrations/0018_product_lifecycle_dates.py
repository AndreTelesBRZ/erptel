from django.db import migrations, models


class Migration(migrations.Migration):

	dependencies = [
		('products', '0017_productsubgroup_parent_subgroup'),
	]

	operations = [
		migrations.AddField(
			model_name='product',
			name='lifecycle_end_date',
			field=models.DateField(blank=True, null=True, verbose_name='Fim de linha'),
		),
		migrations.AddField(
			model_name='product',
			name='lifecycle_start_date',
			field=models.DateField(blank=True, null=True, verbose_name='Início de linha'),
		),
	]
