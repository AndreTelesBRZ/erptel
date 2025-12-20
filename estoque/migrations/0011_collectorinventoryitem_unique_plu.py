from decimal import Decimal

from django.db import migrations
from django.db.models import Count


def deduplicate_collector_items(apps, schema_editor):
    Item = apps.get_model("estoque", "CollectorInventoryItem")
    duplicates = (
        Item.objects.values("plu_code", "loja", "local")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    for group in duplicates:
        entries = list(
            Item.objects.filter(
                plu_code=group["plu_code"],
                loja=group["loja"],
                local=group["local"],
            ).order_by("id")
        )
        primary = entries[0]
        other_items = entries[1:]
        total_quantity = primary.quantidade or Decimal("0")
        merged_counts = list(primary.contagens or [])
        descricao = primary.descricao
        product_id = primary.product_id
        codigo_produto = primary.codigo_produto
        fechado_em = primary.fechado_em

        for item in other_items:
            total_quantity += item.quantidade or Decimal("0")
            merged_counts.extend(item.contagens or [])
            if not descricao and item.descricao:
                descricao = item.descricao
            if not product_id and item.product_id:
                product_id = item.product_id
            if not codigo_produto and item.codigo_produto:
                codigo_produto = item.codigo_produto
            if not fechado_em and item.fechado_em:
                fechado_em = item.fechado_em
            item.delete()

        primary.quantidade = total_quantity.quantize(Decimal("0.001"))
        primary.contagens = merged_counts
        if descricao:
            primary.descricao = descricao[:255]
        if product_id:
            primary.product_id = product_id
        if codigo_produto:
            primary.codigo_produto = codigo_produto[:20]
        if fechado_em:
            primary.fechado_em = fechado_em
        primary.save()


class Migration(migrations.Migration):

    dependencies = [
        ("estoque", "0010_collectorinventoryitem_plu_code"),
    ]

    operations = [
        migrations.RunPython(deduplicate_collector_items, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name="collectorinventoryitem",
            unique_together={("plu_code", "loja", "local")},
        ),
    ]
