BEGIN;

-- ------------------------------------------------------------------
-- 1) CADASTROS COMPARTILHADOS
-- ------------------------------------------------------------------

-- Clientes (cadastro compartilhado)
CREATE TABLE IF NOT EXISTS erp_clientes (
    cliente_codigo VARCHAR(50) PRIMARY KEY,
    cliente_status INTEGER,
    cliente_razao_social TEXT,
    cliente_nome_fantasia TEXT,
    cliente_cnpj_cpf TEXT,
    cliente_tipo_pf_pj TEXT,
    cliente_endereco TEXT,
    cliente_numero TEXT,
    cliente_bairro TEXT,
    cliente_cidade TEXT,
    cliente_uf TEXT,
    cliente_cep TEXT,
    cliente_telefone1 TEXT,
    cliente_telefone2 TEXT,
    cliente_email TEXT,
    cliente_inscricao_municipal TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rowhash BYTEA
);

INSERT INTO erp_clientes (
    cliente_codigo,
    cliente_status,
    cliente_razao_social,
    cliente_nome_fantasia,
    cliente_cnpj_cpf,
    cliente_tipo_pf_pj,
    cliente_endereco,
    cliente_numero,
    cliente_bairro,
    cliente_cidade,
    cliente_uf,
    cliente_cep,
    cliente_telefone1,
    cliente_telefone2,
    cliente_email,
    cliente_inscricao_municipal,
    updated_at,
    rowhash
)
SELECT DISTINCT ON (cliente_codigo)
    cliente_codigo,
    cliente_status,
    cliente_razao_social,
    cliente_nome_fantasia,
    cliente_cnpj_cpf,
    cliente_tipo_pf_pj,
    cliente_endereco,
    cliente_numero,
    cliente_bairro,
    cliente_cidade,
    cliente_uf,
    cliente_cep,
    cliente_telefone1,
    cliente_telefone2,
    cliente_email,
    cliente_inscricao_municipal,
    COALESCE(updated_at, NOW()) AS updated_at,
    rowhash
FROM erp_clientes_vendedores
ORDER BY cliente_codigo, updated_at DESC
ON CONFLICT (cliente_codigo) DO UPDATE SET
    cliente_status = EXCLUDED.cliente_status,
    cliente_razao_social = EXCLUDED.cliente_razao_social,
    cliente_nome_fantasia = EXCLUDED.cliente_nome_fantasia,
    cliente_cnpj_cpf = EXCLUDED.cliente_cnpj_cpf,
    cliente_tipo_pf_pj = EXCLUDED.cliente_tipo_pf_pj,
    cliente_endereco = EXCLUDED.cliente_endereco,
    cliente_numero = EXCLUDED.cliente_numero,
    cliente_bairro = EXCLUDED.cliente_bairro,
    cliente_cidade = EXCLUDED.cliente_cidade,
    cliente_uf = EXCLUDED.cliente_uf,
    cliente_cep = EXCLUDED.cliente_cep,
    cliente_telefone1 = EXCLUDED.cliente_telefone1,
    cliente_telefone2 = EXCLUDED.cliente_telefone2,
    cliente_email = EXCLUDED.cliente_email,
    cliente_inscricao_municipal = EXCLUDED.cliente_inscricao_municipal,
    updated_at = EXCLUDED.updated_at,
    rowhash = EXCLUDED.rowhash;

-- Produtos (cadastro compartilhado)
CREATE TABLE IF NOT EXISTS erp_produtos (
    produto_codigo VARCHAR(50) PRIMARY KEY,
    descricao_completa TEXT,
    referencia VARCHAR(100),
    secao VARCHAR(20),
    grupo VARCHAR(20),
    subgrupo VARCHAR(20),
    unidade VARCHAR(20),
    ean VARCHAR(50),
    plu VARCHAR(50),
    refplu VARCHAR(50),
    row_hash TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO erp_produtos (
    produto_codigo,
    descricao_completa,
    referencia,
    secao,
    grupo,
    subgrupo,
    unidade,
    ean,
    plu,
    refplu,
    row_hash,
    updated_at
)
SELECT DISTINCT ON (codigo)
    codigo AS produto_codigo,
    descricao_completa,
    referencia,
    secao,
    grupo,
    subgrupo,
    unidade,
    ean,
    plu,
    refplu,
    row_hash,
    COALESCE(updated_at, NOW()) AS updated_at
FROM erp_produtos_sync
ORDER BY codigo, updated_at DESC
ON CONFLICT (produto_codigo) DO UPDATE SET
    descricao_completa = EXCLUDED.descricao_completa,
    referencia = EXCLUDED.referencia,
    secao = EXCLUDED.secao,
    grupo = EXCLUDED.grupo,
    subgrupo = EXCLUDED.subgrupo,
    unidade = EXCLUDED.unidade,
    ean = EXCLUDED.ean,
    plu = EXCLUDED.plu,
    refplu = EXCLUDED.refplu,
    row_hash = EXCLUDED.row_hash,
    updated_at = EXCLUDED.updated_at;

-- ------------------------------------------------------------------
-- 2) OPERACIONAL POR LOJA
-- ------------------------------------------------------------------

-- Cliente x Loja (vinculo operacional)
ALTER TABLE erp_clientes_vendedores
    ADD COLUMN IF NOT EXISTS loja_codigo VARCHAR(10);

UPDATE erp_clientes_vendedores
SET loja_codigo = '00001'
WHERE loja_codigo IS NULL;

ALTER TABLE erp_clientes_vendedores
    ALTER COLUMN loja_codigo SET NOT NULL;

ALTER TABLE erp_clientes_vendedores
    DROP CONSTRAINT IF EXISTS erp_clientes_vendedores_pkey;

ALTER TABLE erp_clientes_vendedores
    ADD PRIMARY KEY (cliente_codigo, loja_codigo);

CREATE INDEX IF NOT EXISTS idx_erp_clientes_vendedores_loja
    ON erp_clientes_vendedores (loja_codigo);

CREATE INDEX IF NOT EXISTS idx_erp_clientes_vendedores_vendedor_loja
    ON erp_clientes_vendedores (vendedor_codigo, loja_codigo);

-- Precos (operacional por loja)
CREATE TABLE IF NOT EXISTS erp_produtos_precos (
    produto_codigo VARCHAR(50) NOT NULL,
    loja_codigo VARCHAR(10) NOT NULL,
    preco_normal NUMERIC(18,2),
    preco_promocao1 NUMERIC(18,2),
    preco_promocao2 NUMERIC(18,2),
    custo NUMERIC(18,2),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (produto_codigo, loja_codigo)
);

CREATE INDEX IF NOT EXISTS idx_erp_produtos_precos_loja
    ON erp_produtos_precos (loja_codigo);

-- Estoque (operacional por loja)
CREATE TABLE IF NOT EXISTS erp_produtos_estoque (
    produto_codigo VARCHAR(50) NOT NULL,
    loja_codigo VARCHAR(10) NOT NULL,
    estoque_disponivel NUMERIC(18,3),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (produto_codigo, loja_codigo)
);

CREATE INDEX IF NOT EXISTS idx_erp_produtos_estoque_loja
    ON erp_produtos_estoque (loja_codigo);

INSERT INTO erp_produtos_precos (
    produto_codigo,
    loja_codigo,
    preco_normal,
    preco_promocao1,
    preco_promocao2,
    custo,
    updated_at
)
SELECT
    codigo AS produto_codigo,
    loja AS loja_codigo,
    preco_normal,
    preco_promocao1,
    preco_promocao2,
    custo,
    COALESCE(updated_at, NOW()) AS updated_at
FROM erp_produtos_sync
ON CONFLICT (produto_codigo, loja_codigo) DO UPDATE SET
    preco_normal = EXCLUDED.preco_normal,
    preco_promocao1 = EXCLUDED.preco_promocao1,
    preco_promocao2 = EXCLUDED.preco_promocao2,
    custo = EXCLUDED.custo,
    updated_at = EXCLUDED.updated_at;

INSERT INTO erp_produtos_estoque (
    produto_codigo,
    loja_codigo,
    estoque_disponivel,
    updated_at
)
SELECT
    codigo AS produto_codigo,
    loja AS loja_codigo,
    estoque_disponivel,
    COALESCE(updated_at, NOW()) AS updated_at
FROM erp_produtos_sync
ON CONFLICT (produto_codigo, loja_codigo) DO UPDATE SET
    estoque_disponivel = EXCLUDED.estoque_disponivel,
    updated_at = EXCLUDED.updated_at;

-- Atualiza views para ler das novas tabelas
CREATE OR REPLACE VIEW vw_produtos_sync_preco_estoque AS
SELECT
    p.produto_codigo AS "Codigo",
    p.descricao_completa AS "DescricaoCompleta",
    p.referencia AS "Referencia",
    p.secao AS "Secao",
    p.grupo AS "Grupo",
    p.subgrupo AS "Subgrupo",
    p.unidade AS "Unidade",
    p.ean AS "EAN",
    p.plu AS "PLU",
    pr.preco_normal AS "PrecoNormal",
    pr.preco_promocao1 AS "PrecoPromocional1",
    pr.preco_promocao2 AS "PrecoPromocional2",
    pr.custo AS "Custo",
    pe.estoque_disponivel AS "EstoqueDisponivel",
    pr.loja_codigo AS "Loja",
    p.refplu AS "REFPLU",
    p.row_hash AS "RowHash"
FROM erp_produtos p
JOIN erp_produtos_precos pr
    ON pr.produto_codigo = p.produto_codigo
LEFT JOIN erp_produtos_estoque pe
    ON pe.produto_codigo = p.produto_codigo
   AND pe.loja_codigo = pr.loja_codigo;

CREATE OR REPLACE VIEW vw_produto_imagem AS
SELECT
    p.produto_codigo AS produto_codigo,
    pr.loja_codigo AS loja_codigo,
    COALESCE(ip.codigo, isg.codigo, ig.codigo, ise.codigo) AS codigo_imagem,
    COALESCE(ip.tipo, isg.tipo, ig.tipo, ise.tipo) AS tipo_imagem
FROM erp_produtos p
JOIN erp_produtos_precos pr
    ON pr.produto_codigo = p.produto_codigo
LEFT JOIN erp_imagens ip
    ON ip.tipo::text = 'produto'::text
   AND ip.codigo::text = p.produto_codigo::text
   AND ip.ativo = true
LEFT JOIN erp_imagens isg
    ON isg.tipo::text = 'subgrupo'::text
   AND isg.codigo::text = p.subgrupo::text
   AND isg.ativo = true
LEFT JOIN erp_imagens ig
    ON ig.tipo::text = 'grupo'::text
   AND ig.codigo::text = p.grupo::text
   AND ig.ativo = true
LEFT JOIN erp_imagens ise
    ON ise.tipo::text = 'secao'::text
   AND ise.codigo::text = p.secao::text
   AND ise.ativo = true;

-- Planos de pagamento por loja (operacional)
ALTER TABLE plano_pagamentos_clientes
    ADD COLUMN IF NOT EXISTS loja_codigo VARCHAR(10);

UPDATE plano_pagamentos_clientes
SET loja_codigo = '00001'
WHERE loja_codigo IS NULL;

ALTER TABLE plano_pagamentos_clientes
    ALTER COLUMN loja_codigo SET NOT NULL;

ALTER TABLE plano_pagamentos_clientes
    DROP CONSTRAINT IF EXISTS uniq_plano_pagamentos_clientes;

ALTER TABLE plano_pagamentos_clientes
    ADD CONSTRAINT uniq_plano_pagamentos_clientes
    UNIQUE (cliente_codigo, loja_codigo, plano_codigo);

CREATE INDEX IF NOT EXISTS idx_plano_pag_cli_loja
    ON plano_pagamentos_clientes (loja_codigo);

-- Pedidos / Orcamentos / Comercial (operacional)
ALTER TABLE sales_pedido
    ADD COLUMN IF NOT EXISTS loja_codigo VARCHAR(10);
UPDATE sales_pedido SET loja_codigo = '00001' WHERE loja_codigo IS NULL;
ALTER TABLE sales_pedido ALTER COLUMN loja_codigo SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sales_pedido_loja ON sales_pedido (loja_codigo);

ALTER TABLE sales_itempedido
    ADD COLUMN IF NOT EXISTS loja_codigo VARCHAR(10);
UPDATE sales_itempedido
SET loja_codigo = sp.loja_codigo
FROM sales_pedido sp
WHERE sales_itempedido.pedido_id = sp.id
  AND sales_itempedido.loja_codigo IS NULL;
UPDATE sales_itempedido SET loja_codigo = '00001' WHERE loja_codigo IS NULL;
ALTER TABLE sales_itempedido ALTER COLUMN loja_codigo SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sales_itempedido_loja ON sales_itempedido (loja_codigo);

ALTER TABLE sales_quote
    ADD COLUMN IF NOT EXISTS loja_codigo VARCHAR(10);
UPDATE sales_quote SET loja_codigo = '00001' WHERE loja_codigo IS NULL;
ALTER TABLE sales_quote ALTER COLUMN loja_codigo SET NOT NULL;
ALTER TABLE sales_quote DROP CONSTRAINT IF EXISTS sales_quote_number_key;
ALTER TABLE sales_quote
    ADD CONSTRAINT sales_quote_number_key UNIQUE (number, loja_codigo);
CREATE INDEX IF NOT EXISTS idx_sales_quote_loja ON sales_quote (loja_codigo);

ALTER TABLE sales_quoteitem
    ADD COLUMN IF NOT EXISTS loja_codigo VARCHAR(10);
UPDATE sales_quoteitem
SET loja_codigo = sq.loja_codigo
FROM sales_quote sq
WHERE sales_quoteitem.quote_id = sq.id
  AND sales_quoteitem.loja_codigo IS NULL;
UPDATE sales_quoteitem SET loja_codigo = '00001' WHERE loja_codigo IS NULL;
ALTER TABLE sales_quoteitem ALTER COLUMN loja_codigo SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sales_quoteitem_loja ON sales_quoteitem (loja_codigo);

ALTER TABLE sales_order
    ADD COLUMN IF NOT EXISTS loja_codigo VARCHAR(10);
UPDATE sales_order SET loja_codigo = '00001' WHERE loja_codigo IS NULL;
ALTER TABLE sales_order ALTER COLUMN loja_codigo SET NOT NULL;
ALTER TABLE sales_order DROP CONSTRAINT IF EXISTS sales_order_number_key;
ALTER TABLE sales_order
    ADD CONSTRAINT sales_order_number_key UNIQUE (number, loja_codigo);
CREATE INDEX IF NOT EXISTS idx_sales_order_loja ON sales_order (loja_codigo);

ALTER TABLE sales_orderitem
    ADD COLUMN IF NOT EXISTS loja_codigo VARCHAR(10);
UPDATE sales_orderitem
SET loja_codigo = so.loja_codigo
FROM sales_order so
WHERE sales_orderitem.order_id = so.id
  AND sales_orderitem.loja_codigo IS NULL;
UPDATE sales_orderitem SET loja_codigo = '00001' WHERE loja_codigo IS NULL;
ALTER TABLE sales_orderitem ALTER COLUMN loja_codigo SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sales_orderitem_loja ON sales_orderitem (loja_codigo);

-- Financeiro (operacional)
ALTER TABLE finance_financeentry
    ADD COLUMN IF NOT EXISTS loja_codigo VARCHAR(10);
UPDATE finance_financeentry SET loja_codigo = '00001' WHERE loja_codigo IS NULL;
ALTER TABLE finance_financeentry ALTER COLUMN loja_codigo SET NOT NULL;
CREATE INDEX IF NOT EXISTS idx_finance_financeentry_loja ON finance_financeentry (loja_codigo);

COMMIT;
