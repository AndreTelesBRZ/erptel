from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

	dependencies = [
		('products', '0015_priceadjustmentbatch_priceadjustmentitem'),
		migrations.swappable_dependency(settings.AUTH_USER_MODEL),
	]

	operations = [
		migrations.CreateModel(
			name='PriceAdjustmentLog',
			fields=[
				('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
				('action', models.CharField(choices=[('approved', 'Aprovado'), ('rejected', 'Rejeitado'), ('pending', 'Pendente')], max_length=20)),
				('old_price', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
				('new_price', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
				('notes', models.CharField(blank=True, max_length=255)),
				('created_at', models.DateTimeField(auto_now_add=True)),
				('batch', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='logs', to='products.priceadjustmentbatch')),
				('decided_by', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
				('item', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='logs', to='products.priceadjustmentitem')),
				('product', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='price_adjustment_logs', to='products.product')),
			],
			options={
				'ordering': ('-created_at',),
				'verbose_name': 'Histórico de reajuste',
				'verbose_name_plural': 'Históricos de reajuste',
			},
		),
	]
