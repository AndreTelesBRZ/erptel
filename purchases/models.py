from django.db import models
from django.utils import timezone

from companies.models import Company


class PurchaseOrder(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Rascunho'),
        ('sent', 'Enviada'),
        ('received', 'Recebida'),
        ('cancelled', 'Cancelada'),
    ]

    order_number = models.CharField('Número', max_length=30, unique=True)
    supplier = models.CharField('Fornecedor', max_length=200)
    status = models.CharField('Status', max_length=20, choices=STATUS_CHOICES, default='draft')
    total_amount = models.DecimalField('Valor total', max_digits=14, decimal_places=2, default=0)
    expected_date = models.DateField('Previsão de entrega', blank=True, null=True)
    notes = models.TextField('Observações', blank=True)
    company = models.ForeignKey(Company, related_name='purchase_orders', on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField('Criado em', default=timezone.now, editable=False)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'Pedido de Compra'
        verbose_name_plural = 'Pedidos de Compra'
        ordering = ('-created_at',)

    def __str__(self) -> str:
        return f"{self.order_number} - {self.supplier}"

# Create your models here.
