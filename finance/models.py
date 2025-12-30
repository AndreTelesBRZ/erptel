from django.db import models
from django.utils import timezone


class FinanceEntry(models.Model):
    ENTRY_TYPES = [
        ('receivable', 'Receber'),
        ('payable', 'Pagar'),
    ]

    title = models.CharField('Título', max_length=200)
    category = models.CharField('Categoria', max_length=100, blank=True)
    entry_type = models.CharField('Tipo', max_length=20, choices=ENTRY_TYPES, default='receivable')
    amount = models.DecimalField('Valor', max_digits=14, decimal_places=2)
    due_date = models.DateField('Vencimento', blank=True, null=True)
    paid = models.BooleanField('Liquidado', default=False)
    notes = models.TextField('Observações', blank=True)
    loja_codigo = models.CharField('Loja', max_length=10, default='00001')
    created_at = models.DateTimeField('Criado em', default=timezone.now, editable=False)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'Lançamento financeiro'
        verbose_name_plural = 'Lançamentos financeiros'
        ordering = ('-due_date', '-created_at')

    def __str__(self) -> str:
        suffix = '✓' if self.paid else '•'
        return f"{self.title} ({self.get_entry_type_display()} {suffix})"

# Create your models here.
