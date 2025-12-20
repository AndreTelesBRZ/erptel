from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('products', '0019_supplierproductprice'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplierproductprice',
            name='product',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='supplier_catalogs', to='products.product'),
        ),
    ]
