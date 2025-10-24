from django.db import models


class ProductGroup(models.Model):
	name = models.CharField(max_length=200)

	class Meta:
		verbose_name = 'Grupo de Produtos'
		verbose_name_plural = 'Grupos de Produtos'

	def __str__(self):
		return self.name


class ProductSubGroup(models.Model):
	group = models.ForeignKey(ProductGroup, related_name='subgroups', on_delete=models.CASCADE)
	name = models.CharField(max_length=200)

	class Meta:
		verbose_name = 'Subgrupo de Produtos'
		verbose_name_plural = 'Subgrupos de Produtos'

	def __str__(self):
		return f"{self.group} / {self.name}"


# New related models inferred from spreadsheet
class Supplier(models.Model):
	name = models.CharField(max_length=200)
	code = models.CharField(max_length=200, blank=True, null=True)

	class Meta:
		verbose_name = 'Fornecedor'
		verbose_name_plural = 'Fornecedores'

	def __str__(self):
		return self.name


class Brand(models.Model):
	name = models.CharField(max_length=200)

	class Meta:
		verbose_name = 'Marca'
		verbose_name_plural = 'Marcas'

	def __str__(self):
		return self.name


class Category(models.Model):
	name = models.CharField(max_length=200)

	class Meta:
		verbose_name = 'Categoria'
		verbose_name_plural = 'Categorias'

	def __str__(self):
		return self.name


class Department(models.Model):
	name = models.CharField(max_length=200)

	class Meta:
		verbose_name = 'Departamento'
		verbose_name_plural = 'Departamentos'

	def __str__(self):
		return self.name


class Tag(models.Model):
	name = models.CharField(max_length=200)

	class Meta:
		verbose_name = 'Tag'
		verbose_name_plural = 'Tags'

	def __str__(self):
		return self.name


class Tax(models.Model):
	name = models.CharField(max_length=200)
	code = models.CharField(max_length=200, blank=True, null=True)

	class Meta:
		verbose_name = 'Tributo'
		verbose_name_plural = 'Tributos'

	def __str__(self):
		return self.name


class Volume(models.Model):
	description = models.CharField(max_length=200)

	class Meta:
		verbose_name = 'Volume'
		verbose_name_plural = 'Volumes'

	def __str__(self):
		return self.description


class UnitOfMeasure(models.Model):
	code = models.CharField(max_length=50)
	name = models.CharField(max_length=100, blank=True, null=True)

	class Meta:
		verbose_name = 'Unidade de Medida'
		verbose_name_plural = 'Unidades de Medida'

	def __str__(self):
		return self.code


class ProductImage(models.Model):
	product = models.ForeignKey('Product', related_name='images', on_delete=models.CASCADE)
	url = models.TextField()

	class Meta:
		verbose_name = 'Imagem do Produto'
		verbose_name_plural = 'Imagens dos Produtos'

	def __str__(self):
		return f"Imagem de {self.product}"


class Product(models.Model):
	name = models.CharField(max_length=200)
	code = models.CharField(max_length=100, blank=True, null=True)  # Código
	description = models.TextField(blank=True)
	short_description = models.CharField(max_length=255, blank=True, null=True)
	unit = models.CharField(max_length=50, blank=True, null=True)  # Unidade
	ncm = models.CharField(max_length=50, blank=True, null=True)
	origin = models.CharField(max_length=10, blank=True, null=True)  # Origem
	price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
	fixed_ipi = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
	status = models.CharField(max_length=50, blank=True, null=True)
	stock = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
	cost_price = models.DecimalField(max_digits=14, decimal_places=4, blank=True, null=True)
	supplier_code = models.CharField(max_length=200, blank=True, null=True)
	supplier = models.CharField(max_length=200, blank=True, null=True)
	location = models.CharField(max_length=200, blank=True, null=True)
	max_stock = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
	min_stock = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
	weight_net = models.DecimalField(max_digits=10, decimal_places=3, blank=True, null=True)
	weight_gross = models.DecimalField(max_digits=10, decimal_places=3, blank=True, null=True)
	gtin = models.CharField(max_length=100, blank=True, null=True)
	gtin_package = models.CharField(max_length=100, blank=True, null=True)
	width = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
	height = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
	depth = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
	expiration_date = models.DateField(blank=True, null=True)
	supplier_description = models.TextField(blank=True, null=True)
	complement_description = models.TextField(blank=True, null=True)
	items_per_box = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
	variation = models.CharField(max_length=200, blank=True, null=True)
	production_type = models.CharField(max_length=200, blank=True, null=True)
	ipi_class = models.CharField(max_length=200, blank=True, null=True)
	service_list_code = models.CharField(max_length=200, blank=True, null=True)
	item_type = models.CharField(max_length=200, blank=True, null=True)
	tags = models.CharField(max_length=500, blank=True, null=True)
	taxes = models.CharField(max_length=500, blank=True, null=True)
	parent_code = models.CharField(max_length=200, blank=True, null=True)
	integration_code = models.CharField(max_length=200, blank=True, null=True)
	product_group = models.ForeignKey(ProductGroup, related_name='products', on_delete=models.SET_NULL, blank=True, null=True)
	product_subgroup = models.ForeignKey(ProductSubGroup, related_name='products', on_delete=models.SET_NULL, blank=True, null=True)
	brand = models.CharField(max_length=200, blank=True, null=True)
	brand_obj = models.ForeignKey('Brand', related_name='products', on_delete=models.SET_NULL, blank=True, null=True)
	cest = models.CharField(max_length=200, blank=True, null=True)
	volumes = models.CharField(max_length=200, blank=True, null=True)
	volumes_obj = models.ForeignKey('Volume', related_name='products', on_delete=models.SET_NULL, blank=True, null=True)
	external_images = models.TextField(blank=True, null=True)
	external_link = models.URLField(blank=True, null=True)
	warranty_months = models.IntegerField(blank=True, null=True)
	clone_parent = models.BooleanField(default=False)
	condition = models.CharField(max_length=100, blank=True, null=True)
	free_shipping = models.BooleanField(default=False)
	fci_number = models.CharField(max_length=200, blank=True, null=True)
	video = models.CharField(max_length=500, blank=True, null=True)
	department = models.CharField(max_length=200, blank=True, null=True)
	department_obj = models.ForeignKey('Department', related_name='products', on_delete=models.SET_NULL, blank=True, null=True)
	unit_of_measure = models.CharField(max_length=50, blank=True, null=True)
	unit_of_measure_obj = models.ForeignKey('UnitOfMeasure', related_name='products', on_delete=models.SET_NULL, blank=True, null=True)
	icms_base_st = models.DecimalField(max_digits=14, decimal_places=4, blank=True, null=True)
	icms_st_value = models.DecimalField(max_digits=14, decimal_places=4, blank=True, null=True)
	icms_substitute_value = models.DecimalField(max_digits=14, decimal_places=4, blank=True, null=True)
	category = models.CharField(max_length=200, blank=True, null=True)
	category_obj = models.ForeignKey('Category', related_name='products', on_delete=models.SET_NULL, blank=True, null=True)
	additional_info = models.TextField(blank=True, null=True)
	supplier_obj = models.ForeignKey('Supplier', related_name='products', on_delete=models.SET_NULL, blank=True, null=True)

	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		verbose_name = 'Produto'
		verbose_name_plural = 'Produtos'

	def __str__(self):
		return f"{self.name} ({self.code or '—'})"

