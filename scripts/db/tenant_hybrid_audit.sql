-- Audit: listar tabelas operacionais sem loja_codigo
WITH operacionais(table_name) AS (
    VALUES
        ('erp_clientes_vendedores'),
        ('erp_produtos_precos'),
        ('erp_produtos_estoque'),
        ('plano_pagamentos_clientes'),
        ('sales_pedido'),
        ('sales_itempedido'),
        ('sales_quote'),
        ('sales_quoteitem'),
        ('sales_order'),
        ('sales_orderitem'),
        ('finance_financeentry')
)
SELECT o.table_name
FROM operacionais o
LEFT JOIN information_schema.columns c
    ON c.table_schema = 'public'
   AND c.table_name = o.table_name
   AND c.column_name = 'loja_codigo'
WHERE c.column_name IS NULL
ORDER BY o.table_name;

-- Audit: verificar cadastros que nao podem ter loja_codigo
WITH cadastros(table_name) AS (
    VALUES
        ('erp_clientes'),
        ('erp_produtos')
)
SELECT c.table_name
FROM cadastros c
JOIN information_schema.columns col
    ON col.table_schema = 'public'
   AND col.table_name = c.table_name
   AND col.column_name = 'loja_codigo';

-- Audit: registros operacionais com loja_codigo NULL
SELECT 'erp_clientes_vendedores' AS table_name, COUNT(*) AS null_loja
FROM erp_clientes_vendedores WHERE loja_codigo IS NULL
UNION ALL
SELECT 'erp_produtos_precos', COUNT(*) FROM erp_produtos_precos WHERE loja_codigo IS NULL
UNION ALL
SELECT 'erp_produtos_estoque', COUNT(*) FROM erp_produtos_estoque WHERE loja_codigo IS NULL
UNION ALL
SELECT 'plano_pagamentos_clientes', COUNT(*) FROM plano_pagamentos_clientes WHERE loja_codigo IS NULL
UNION ALL
SELECT 'sales_pedido', COUNT(*) FROM sales_pedido WHERE loja_codigo IS NULL
UNION ALL
SELECT 'sales_itempedido', COUNT(*) FROM sales_itempedido WHERE loja_codigo IS NULL
UNION ALL
SELECT 'sales_quote', COUNT(*) FROM sales_quote WHERE loja_codigo IS NULL
UNION ALL
SELECT 'sales_quoteitem', COUNT(*) FROM sales_quoteitem WHERE loja_codigo IS NULL
UNION ALL
SELECT 'sales_order', COUNT(*) FROM sales_order WHERE loja_codigo IS NULL
UNION ALL
SELECT 'sales_orderitem', COUNT(*) FROM sales_orderitem WHERE loja_codigo IS NULL
UNION ALL
SELECT 'finance_financeentry', COUNT(*) FROM finance_financeentry WHERE loja_codigo IS NULL;

-- Audit: colisao cross-tenant (exemplo de chaves compostas)
SELECT cliente_codigo, loja_codigo, COUNT(*)
FROM erp_clientes_vendedores
GROUP BY cliente_codigo, loja_codigo
HAVING COUNT(*) > 1;

SELECT produto_codigo, loja_codigo, COUNT(*)
FROM erp_produtos_precos
GROUP BY produto_codigo, loja_codigo
HAVING COUNT(*) > 1;

SELECT produto_codigo, loja_codigo, COUNT(*)
FROM erp_produtos_estoque
GROUP BY produto_codigo, loja_codigo
HAVING COUNT(*) > 1;
