from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0008_pedido_itempedido'),
    ]

    operations = [
        migrations.AddField(
            model_name='pedido',
            name='frete_modalidade',
            field=models.CharField(
                choices=[('cif', 'CIF'), ('fob', 'FOB'), ('sem_frete', 'Sem frete')],
                default='sem_frete',
                max_length=20,
                verbose_name='Modalidade de frete',
            ),
        ),
        migrations.AddField(
            model_name='pedido',
            name='forma_pagamento',
            field=models.CharField(blank=True, max_length=50, verbose_name='Forma de pagamento'),
        ),
        migrations.AddField(
            model_name='pedido',
            name='pagamento_status',
            field=models.CharField(
                choices=[
                    ('aguardando', 'Aguardando pagamento'),
                    ('pago_avista', 'Pagamento à vista'),
                    ('fatura_a_vencer', 'Fatura a vencer'),
                    ('negado', 'Pagamento negado'),
                ],
                default='aguardando',
                max_length=20,
                verbose_name='Status do pagamento',
            ),
        ),
        migrations.AddField(
            model_name='pedido',
            name='status',
            field=models.CharField(
                choices=[
                    ('orcamento', 'Orçamento'),
                    ('pre_venda', 'Pré-venda (Enviada)'),
                    ('em_separacao', 'Pedido em Separação'),
                    ('faturado', 'Pedido Faturado'),
                    ('entregue', 'Pedido Entregue'),
                    ('cancelado', 'Cancelado'),
                ],
                default='pre_venda',
                max_length=20,
                verbose_name='Status',
            ),
        ),
    ]
