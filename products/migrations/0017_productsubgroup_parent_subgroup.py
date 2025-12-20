from django.db import migrations, models


class Migration(migrations.Migration):

	dependencies = [
		('products', '0016_priceadjustmentlog'),
	]

	operations = [
		migrations.AddField(
			model_name='productsubgroup',
			name='parent_subgroup',
			field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.CASCADE, related_name='children', to='products.productsubgroup'),
		),
		migrations.AlterUniqueTogether(
			name='productsubgroup',
			unique_together={('group', 'parent_subgroup', 'name')},
		),
	]
