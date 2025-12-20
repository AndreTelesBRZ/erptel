from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

	dependencies = [
		('products', '0018_product_lifecycle_dates'),
	]

	operations = [
		migrations.CreateModel(
			name='SupplierProductPrice',
			fields=[
				('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
				('code', models.CharField(max_length=100, verbose_name='Código')),
				('description', models.CharField(max_length=255, verbose_name='Descrição')),
				('unit', models.CharField(blank=True, max_length=50, verbose_name='Unidade')),
				('quantity', models.DecimalField(blank=True, decimal_places=3, max_digits=10, null=True, verbose_name='Qtd. etiq.')),
				('pack_quantity', models.DecimalField(blank=True, decimal_places=3, max_digits=10, null=True, verbose_name='Qtd. por embalagem')),
				('unit_price', models.DecimalField(decimal_places=4, max_digits=14, verbose_name='Valor unitário')),
				('ipi_percent', models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True, verbose_name='IPI (%)')),
				('freight_percent', models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True, verbose_name='Frete (%)')),
				('st_percent', models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True, verbose_name='ST (%)')),
				('replacement_cost', models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True, verbose_name='Custo reposição')),
				('valid_from', models.DateField(verbose_name='Início vigência')),
				('valid_until', models.DateField(blank=True, null=True, verbose_name='Fim vigência')),
				('created_at', models.DateTimeField(auto_now_add=True)),
				('updated_at', models.DateTimeField(auto_now=True)),
				('supplier', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='catalog_items', to='products.supplier')),
			],
			options={
				'verbose_name': 'Preço de fornecedor',
				'verbose_name_plural': 'Preços de fornecedores',
				'ordering': ('supplier', 'code', '-valid_from'),
			},
		),
		migrations.AlterUniqueTogether(
			name='supplierproductprice',
			unique_together={('supplier', 'code', 'valid_from')},
		),
	]
