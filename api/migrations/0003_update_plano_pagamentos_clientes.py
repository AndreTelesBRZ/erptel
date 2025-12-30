from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0002_erp_lojas"),
    ]

    operations = [
        migrations.RenameField(
            model_name="planopagamentocliente",
            old_name="descricao",
            new_name="plano_descricao",
        ),
        migrations.RenameField(
            model_name="planopagamentocliente",
            old_name="quantidade_parcelas",
            new_name="parcelas",
        ),
        migrations.RenameField(
            model_name="planopagamentocliente",
            old_name="intervalo_parcelas",
            new_name="dias_entre_parcelas",
        ),
        migrations.RemoveField(
            model_name="planopagamentocliente",
            name="entrada_percentual",
        ),
        migrations.RemoveField(
            model_name="planopagamentocliente",
            name="intervalo_primeira_parcela",
        ),
    ]
