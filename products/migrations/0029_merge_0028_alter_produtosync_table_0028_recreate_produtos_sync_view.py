from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0028_alter_produtosync_table"),
        ("products", "0028_recreate_produtos_sync_view"),
    ]

    operations = []
