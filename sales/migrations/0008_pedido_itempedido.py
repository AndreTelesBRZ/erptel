from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0001_initial'),
        ('products', '0001_initial'),
        ('sales', '0007_quoteitem_delivery_days'),
    ]

    operations = [
        migrations.CreateModel(
            name='Pedido',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('data_criacao', models.DateTimeField()),
                ('total', models.DecimalField(decimal_places=2, max_digits=10)),
                ('data_recebimento', models.DateTimeField(auto_now_add=True)),
                ('cliente', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='pedidos_mobile', to='clients.client')),
            ],
            options={
                'verbose_name': 'Pedido (API)',
                'verbose_name_plural': 'Pedidos (API)',
            },
        ),
        migrations.CreateModel(
            name='ItemPedido',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantidade', models.DecimalField(decimal_places=2, max_digits=10)),
                ('valor_unitario', models.DecimalField(decimal_places=2, max_digits=10)),
                ('pedido', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='itens', to='sales.pedido')),
                ('produto', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='products.product')),
            ],
            options={
                'verbose_name': 'Item do Pedido (API)',
                'verbose_name_plural': 'Itens do Pedido (API)',
            },
        ),
    ]
