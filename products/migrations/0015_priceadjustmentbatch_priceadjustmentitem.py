from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('products', '0014_product_allow_fractional_sale'),
    ]

    operations = [
        migrations.CreateModel(
            name='PriceAdjustmentBatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('pending', 'Pendente'), ('approved', 'Aprovado'), ('rejected', 'Rejeitado')], default='pending', max_length=20)),
                ('rule_type', models.CharField(choices=[('increase_percent', 'Aumentar % sobre o preço atual'), ('set_margin', 'Aplicar margem (%) sobre o custo')], max_length=30)),
                ('parameters', models.JSONField(blank=True, default=dict)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='price_adjustment_batches', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-created_at',),
                'verbose_name': 'Lote de reajuste de preço',
                'verbose_name_plural': 'Lotes de reajuste de preço',
            },
        ),
        migrations.CreateModel(
            name='PriceAdjustmentItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('pending', 'Pendente'), ('skipped', 'Ignorado')], default='pending', max_length=20)),
                ('message', models.CharField(blank=True, max_length=255)),
                ('old_price', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ('new_price', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ('cost_value', models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True)),
                ('old_margin_percent', models.DecimalField(blank=True, decimal_places=2, max_digits=9, null=True)),
                ('new_margin_percent', models.DecimalField(blank=True, decimal_places=2, max_digits=9, null=True)),
                ('rule_snapshot', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='products.priceadjustmentbatch')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='price_adjustments', to='products.product')),
            ],
            options={
                'ordering': ('product__name',),
                'verbose_name': 'Item do reajuste de preço',
                'verbose_name_plural': 'Itens do reajuste de preço',
            },
        ),
    ]
