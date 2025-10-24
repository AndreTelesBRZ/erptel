import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from django.db import transaction
from .models import Product, ProductGroup
from .models import Supplier, Brand, Category, Department, Volume, UnitOfMeasure


def parse_decimal(value):
    if value is None:
        return None
    v = str(value).strip()
    if v == '':
        return None
    v = v.replace('.', '').replace(',', '.') if ',' in v else v
    try:
        return Decimal(v)
    except InvalidOperation:
        return None


@transaction.atomic
def import_products_from_file(file_like):
    """Import products from a file-like object (CSV, delimiter=';').
    Returns (created, updated, messages)
    """
    created = 0
    updated = 0
    messages = []
    # file_like can be path or file object
    if isinstance(file_like, (str, Path)):
        fh = open(file_like, newline='', encoding='utf-8')
        close_after = True
    else:
        fh = file_like
        close_after = False

    try:
        reader = csv.DictReader(fh, delimiter=';')
        for row in reader:
            code = row.get('Código') or row.get('Codigo') or (row.get('Código ') if 'Código ' in row else None)
            name = row.get('Descrição') or row.get('Descricao') or row.get('Descrição do Produto no Fornecedor')
            if not name:
                name = f"Produto {row.get('ID') or ''}".strip()

            group_name = row.get('Grupo de produtos') or row.get('Grupo de produtos ')
            brand = row.get('Marca')

            group = None
            if group_name:
                group, _ = ProductGroup.objects.get_or_create(name=group_name.strip())

            # create/associate related objects
            brand_obj = None
            if brand:
                brand_obj, _ = Brand.objects.get_or_create(name=brand.strip())

            supplier_name = row.get('Fornecedor')
            supplier_obj = None
            if supplier_name:
                supplier_obj, _ = Supplier.objects.get_or_create(name=supplier_name.strip())

            category_name = row.get('Categoria do produto')
            category_obj = None
            if category_name:
                category_obj, _ = Category.objects.get_or_create(name=category_name.strip())

            department_name = row.get('Departamento')
            department_obj = None
            if department_name:
                department_obj, _ = Department.objects.get_or_create(name=department_name.strip())

            volumes_name = row.get('Volumes')
            volumes_obj = None
            if volumes_name:
                volumes_obj, _ = Volume.objects.get_or_create(description=volumes_name.strip())

            uom_name = row.get('Unidade de Medida')
            uom_obj = None
            if uom_name:
                uom_obj, _ = UnitOfMeasure.objects.get_or_create(code=uom_name.strip())

            product = None
            if code:
                product = Product.objects.filter(code=code.strip()).first()
            if not product:
                product = Product.objects.filter(name__iexact=name.strip()).first()

            data = {}
            data['code'] = code.strip() if code else None
            data['name'] = name.strip()
            data['short_description'] = row.get('Descrição Curta')
            data['unit'] = row.get('Unidade')
            data['ncm'] = row.get('NCM')
            data['origin'] = row.get('Origem')
            data['price'] = parse_decimal(row.get('Preço') or row.get('Preco')) or 0
            data['fixed_ipi'] = parse_decimal(row.get('Valor IPI fixo'))
            data['status'] = row.get('Situação')
            data['stock'] = parse_decimal(row.get('Estoque'))
            data['cost_price'] = parse_decimal(row.get('Preço de custo') or row.get('Preco de custo'))
            data['supplier_code'] = row.get('Cód. no fornecedor')
            data['supplier'] = row.get('Fornecedor')
            data['location'] = row.get('Localização')
            data['max_stock'] = parse_decimal(row.get('Estoque máximo') or row.get('Estoque maximo'))
            data['min_stock'] = parse_decimal(row.get('Estoque mínimo') or row.get('Estoque minimo'))
            data['weight_net'] = parse_decimal(row.get('Peso líquido (Kg)'))
            data['weight_gross'] = parse_decimal(row.get('Peso bruto (Kg)'))
            data['gtin'] = row.get('GTIN/EAN')
            data['gtin_package'] = row.get('GTIN/EAN da Embalagem')
            data['width'] = parse_decimal(row.get('Largura do produto'))
            data['height'] = parse_decimal(row.get('Altura do Produto'))
            data['depth'] = parse_decimal(row.get('Profundidade do produto'))
            data['supplier_description'] = row.get('Descrição do Produto no Fornecedor')
            data['complement_description'] = row.get('Descrição Complementar')
            data['items_per_box'] = parse_decimal(row.get('Itens p/ caixa'))
            data['variation'] = row.get('Produto Variação')
            data['production_type'] = row.get('Tipo Produção')
            data['ipi_class'] = row.get('Classe de enquadramento do IPI')
            data['service_list_code'] = row.get('Código na Lista de Serviços')
            data['item_type'] = row.get('Tipo do item')
            data['tags'] = row.get('Grupo de Tags/Tags')
            data['taxes'] = row.get('Tributos')
            data['parent_code'] = row.get('Código Pai')
            data['integration_code'] = row.get('Código Integração')
            data['brand'] = brand
            data['cest'] = row.get('CEST')
            data['volumes'] = row.get('Volumes')
            data['external_images'] = row.get('URL Imagens Externas')
            data['external_link'] = row.get('Link Externo')
            data['clone_parent'] = True if (row.get('Clonar dados do pai') or '').strip().upper() in ('SIM','S','1','TRUE') else False
            data['condition'] = row.get('Condição do Produto')
            data['free_shipping'] = True if (row.get('Frete Grátis') or '').strip().upper() in ('SIM','S','1','TRUE') else False
            data['fci_number'] = row.get('Número FCI')
            data['video'] = row.get('Vídeo')
            data['department'] = row.get('Departamento')
            data['unit_of_measure'] = row.get('Unidade de Medida')
            data['icms_base_st'] = parse_decimal(row.get('Valor base ICMS ST para retenção'))
            data['icms_st_value'] = parse_decimal(row.get('Valor ICMS ST para retenção'))
            data['icms_substitute_value'] = parse_decimal(row.get('Valor ICMS próprio do substituto'))
            data['category'] = row.get('Categoria do produto')
            data['additional_info'] = row.get('Informações Adicionais')

            if group:
                data['product_group'] = group

            if brand_obj:
                data['brand_obj'] = brand_obj

            if supplier_obj:
                data['supplier_obj'] = supplier_obj

            if category_obj:
                data['category_obj'] = category_obj

            if department_obj:
                data['department_obj'] = department_obj

            if volumes_obj:
                data['volumes_obj'] = volumes_obj

            if uom_obj:
                data['unit_of_measure_obj'] = uom_obj

            if product:
                for k, v in data.items():
                    setattr(product, k, v)
                product.save()
                updated += 1
                messages.append(f"Updated product: {product.name} (code={product.code})")
            else:
                product = Product.objects.create(**data)
                created += 1
                messages.append(f"Created product: {product.name} (code={product.code})")

    finally:
        if close_after:
            fh.close()

    return created, updated, messages
