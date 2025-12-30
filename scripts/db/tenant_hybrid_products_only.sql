BEGIN;

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

COMMIT;
