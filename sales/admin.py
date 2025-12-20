from django.contrib import admin

from .models import Quote, QuoteItem, Order, OrderItem, Salesperson, Pedido, ItemPedido


class QuoteItemInline(admin.TabularInline):
	model = QuoteItem
	extra = 0


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
	list_display = ('number', 'client', 'salesperson', 'status', 'created_at', 'total_amount')
	list_filter = ('status', 'created_at', 'salesperson')
	search_fields = ('number', 'client__first_name', 'client__last_name', 'client__email', 'salesperson__user__first_name', 'salesperson__user__last_name')
	inlines = [QuoteItemInline]


class OrderItemInline(admin.TabularInline):
	model = OrderItem
	extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
	list_display = ('number', 'client', 'status', 'issue_date', 'created_at', 'total_amount')
	list_filter = ('status', 'issue_date', 'created_at')
	search_fields = ('number', 'client__first_name', 'client__last_name', 'client__email')
	inlines = [OrderItemInline]


@admin.register(Salesperson)
class SalespersonAdmin(admin.ModelAdmin):
	list_display = ('user', 'phone', 'is_active', 'created_at')
	list_filter = ('is_active',)
	search_fields = ('user__username', 'user__first_name', 'user__last_name', 'user__email', 'phone')


class ItemPedidoInline(admin.TabularInline):
	model = ItemPedido
	extra = 0


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
	list_display = (
		'id',
		'cliente',
		'vendedor_codigo',
		'status',
		'pagamento_status',
		'frete_modalidade',
		'data_criacao',
		'data_recebimento',
		'total',
	)
	list_filter = ('status', 'pagamento_status', 'frete_modalidade', 'data_recebimento')
	search_fields = ('cliente__first_name', 'cliente__last_name', 'cliente__code', 'cliente__cpf', 'vendedor_codigo', 'vendedor_nome')
	inlines = [ItemPedidoInline]
