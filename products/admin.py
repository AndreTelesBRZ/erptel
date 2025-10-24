from django.contrib import admin
from .models import (
	Product,
	ProductGroup,
	ProductSubGroup,
	Supplier,
	Brand,
	Category,
	Department,
	Tag,
	Tax,
	Volume,
	UnitOfMeasure,
	ProductImage,
)


@admin.register(ProductGroup)
class ProductGroupAdmin(admin.ModelAdmin):
	list_display = ("name",)
	search_fields = ("name",)


@admin.register(ProductSubGroup)
class ProductSubGroupAdmin(admin.ModelAdmin):
	list_display = ("name", "group")
	search_fields = ("name", "group__name")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
	list_display = ("name", "code", "price", "stock", "product_group", "product_subgroup", "created_at")
	search_fields = ("name", "code", "supplier", "brand")
	list_filter = ("product_group", "product_subgroup", "brand", "status")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
	list_display = ("name", "code")


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
	list_display = ("name",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
	list_display = ("name",)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
	list_display = ("name",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
	list_display = ("name",)


@admin.register(Tax)
class TaxAdmin(admin.ModelAdmin):
	list_display = ("name", "code")


@admin.register(Volume)
class VolumeAdmin(admin.ModelAdmin):
	list_display = ("description",)


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
	list_display = ("code", "name")


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
	list_display = ("product", "url")
