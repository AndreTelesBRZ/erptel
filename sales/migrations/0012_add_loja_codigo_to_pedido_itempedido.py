from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0011_auto_20251224_1738'),
    ]

    operations = [
        migrations.AddField(
            model_name='pedido',
            name='loja_codigo',
            field=models.CharField(default='00001', max_length=10, verbose_name='Loja'),
        ),
        migrations.AddField(
            model_name='itempedido',
            name='loja_codigo',
            field=models.CharField(default='00001', max_length=10, verbose_name='Loja'),
        ),
    ]
