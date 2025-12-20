from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from products.models import Product, ProductStock
from purchases.models import PurchaseOrder
from sales.models import Order, OrderItem, Quote, QuoteItem

ZERO_DECIMAL = Decimal("0.00")


def _decimal(value: Decimal | None) -> Decimal:
    """Return a Decimal zero when the value is falsy."""
    if value is None:
        return ZERO_DECIMAL
    return value


def _counts_by_status(queryset, field_name: str, choices: list[tuple[str, str]]):
    counts = {
        row[field_name]: row["total"]
        for row in queryset.values(field_name).annotate(total=Count("id"))
    }
    return [
        {
            "code": code,
            "label": label,
            "count": counts.get(code, 0),
        }
        for code, label in choices
    ]


def get_sales_report(company=None) -> dict:
    today = timezone.localdate()
    last_30_days = today - timedelta(days=30)

    company_id = getattr(company, "pk", company)

    orders = Order.objects.all()
    quotes = Quote.objects.all()
    order_items = OrderItem.objects.all()
    quote_items = QuoteItem.objects.all()

    if company_id:
        orders = orders.filter(company_id=company_id)
        quotes = quotes.filter(company_id=company_id)
        order_items = order_items.filter(order__company_id=company_id)
        quote_items = quote_items.filter(quote__company_id=company_id)

    order_total_expr = ExpressionWrapper(
        F("quantity") * F("unit_price") - Coalesce(F("discount"), Value(ZERO_DECIMAL)),
        output_field=DecimalField(max_digits=16, decimal_places=2),
    )
    quote_total_expr = ExpressionWrapper(
        F("quantity") * F("unit_price") - Coalesce(F("discount"), Value(ZERO_DECIMAL)),
        output_field=DecimalField(max_digits=16, decimal_places=2),
    )

    total_order_value = _decimal(order_items.aggregate(total=Sum(order_total_expr))["total"])
    total_quote_value = _decimal(quote_items.aggregate(total=Sum(quote_total_expr))["total"])

    recent_order_value = _decimal(
        order_items.filter(order__issue_date__gte=last_30_days).aggregate(total=Sum(order_total_expr))["total"]
    )
    recent_quote_value = _decimal(
        quote_items.filter(quote__created_at__date__gte=last_30_days).aggregate(total=Sum(quote_total_expr))["total"]
    )

    order_status = _counts_by_status(orders, "status", Order.Status.choices)
    quote_status = _counts_by_status(quotes, "status", Quote.Status.choices)

    conversion_rate = Decimal("0")
    approved_quotes = next((item["count"] for item in quote_status if item["code"] == Quote.Status.APPROVED), 0)
    converted_quotes = next((item["count"] for item in quote_status if item["code"] == Quote.Status.CONVERTED), 0)
    if approved_quotes:
        conversion_rate = Decimal(converted_quotes) / Decimal(approved_quotes) * Decimal("100")

    return {
        "summary": {
            "total_orders": orders.count(),
            "total_quotes": quotes.count(),
            "total_order_value": total_order_value,
            "total_quote_value": total_quote_value,
            "conversion_rate": conversion_rate.quantize(Decimal("0.01")) if conversion_rate else Decimal("0.00"),
        },
        "last_30_days": {
            "order_value": recent_order_value,
            "quote_value": recent_quote_value,
            "orders": orders.filter(issue_date__gte=last_30_days).count(),
            "quotes": quotes.filter(created_at__date__gte=last_30_days).count(),
        },
        "status_breakdown": {
            "orders": order_status,
            "quotes": quote_status,
        },
    }


def get_purchase_report(company=None) -> dict:
    today = timezone.localdate()
    last_30_days = today - timedelta(days=30)
    company_id = getattr(company, "pk", company)
    purchases = PurchaseOrder.objects.all()
    if company_id:
        purchases = purchases.filter(company_id=company_id)
    status_breakdown = _counts_by_status(purchases, "status", PurchaseOrder.STATUS_CHOICES)
    totals = purchases.aggregate(total=Coalesce(Sum("total_amount"), Value(ZERO_DECIMAL)))
    recent_total = purchases.filter(created_at__date__gte=last_30_days).aggregate(
        total=Coalesce(Sum("total_amount"), Value(ZERO_DECIMAL))
    )
    return {
        "summary": {
            "total_orders": purchases.count(),
            "total_amount": _decimal(totals["total"]),
        },
        "last_30_days": {
            "orders": purchases.filter(created_at__date__gte=last_30_days).count(),
            "amount": _decimal(recent_total["total"]),
        },
        "status_breakdown": status_breakdown,
    }


def get_product_report(company=None) -> dict:
    company_id = getattr(company, "pk", company)

    if company_id:
        stocks = ProductStock.objects.filter(company_id=company_id).select_related("product")
    else:
        stocks = ProductStock.objects.select_related("product")

    value_expr = ExpressionWrapper(
        Coalesce(F("quantity"), Value(ZERO_DECIMAL)) * Coalesce(F("product__price"), Value(ZERO_DECIMAL)),
        output_field=DecimalField(max_digits=16, decimal_places=2),
    )
    inventory_value = _decimal(stocks.aggregate(total=Sum(value_expr))["total"])

    if company_id:
        product_count = stocks.count()
        price_total = Product.objects.filter(pk__in=stocks.values_list("product_id", flat=True)).aggregate(
            total=Coalesce(Sum("price"), Value(ZERO_DECIMAL))
        )["total"] or ZERO_DECIMAL
    else:
        product_count = Product.objects.count()
        price_total = Product.objects.aggregate(total=Coalesce(Sum("price"), Value(ZERO_DECIMAL)))['total'] or ZERO_DECIMAL

    avg_price = Decimal("0.00")
    if product_count:
        avg_price = _decimal(price_total) / Decimal(product_count)

    if company_id:
        low_stock = stocks.filter(min_quantity__gt=0, quantity__lt=F("min_quantity")).count()
        no_stock = stocks.filter(quantity__lte=0).count()
    else:
        low_stock = stocks.filter(min_quantity__gt=0, quantity__lt=F("min_quantity")).count()
        no_stock = stocks.filter(quantity__lte=0).count()

    return {
        "summary": {
            "total_products": product_count,
            "inventory_value": inventory_value,
            "average_price": avg_price.quantize(Decimal("0.01")) if avg_price else ZERO_DECIMAL,
        },
        "stock": {
            "low_stock": low_stock,
            "out_of_stock": no_stock,
        },
    }


def get_report_context(company=None) -> dict:
    return {
        "sales_report": get_sales_report(company=company),
        "purchase_report": get_purchase_report(company=company),
        "product_report": get_product_report(company=company),
    }
