INSERT INTO plano_pagamento_cliente
(cliente_codigo, loja_codigo, plano_codigo, plano_descricao, parcelas, dias_entre_parcelas, valor_minimo, valor_acrescimo, updated_at)
VALUES
('todos', '00001', 'DINHEIRO', 'Dinheiro', 0, 0, 0, 0, NOW()),
('todos', '00003', 'DINHEIRO', 'Dinheiro', 0, 0, 0, 0, NOW()),

('todos', '00001', 'PIX', 'PIX', 0, 0, 0, 0, NOW()),
('todos', '00003', 'PIX', 'PIX', 0, 0, 0, 0, NOW()),

('todos', '00001', 'BOLETO_7', 'Boleto 7', 1, 7, 150, 0, NOW()),
('todos', '00003', 'BOLETO_7', 'Boleto 7', 1, 7, 150, 0, NOW()),

('todos', '00001', 'BOLETO_14', 'Boleto 14', 1, 14, 150, 0, NOW()),
('todos', '00003', 'BOLETO_14', 'Boleto 14', 1, 14, 150, 0, NOW()),

('todos', '00001', 'BOLETO_21', 'Boleto 21', 1, 21, 150, 0, NOW()),
('todos', '00003', 'BOLETO_21', 'Boleto 21', 1, 21, 150, 0, NOW()),

('todos', '00001', 'BOLETO_28', 'Boleto 28', 1, 28, 150, 0, NOW()),
('todos', '00003', 'BOLETO_28', 'Boleto 28', 1, 28, 150, 0, NOW()),

('todos', '00001', 'BOLETO_30', 'Boleto 30', 1, 30, 150, 0, NOW()),
('todos', '00003', 'BOLETO_30', 'Boleto 30', 1, 30, 150, 0, NOW()),

('todos', '00001', 'BOLETO_30_45', 'Boleto 30/45', 2, 15, 300, 0, NOW()),
('todos', '00003', 'BOLETO_30_45', 'Boleto 30/45', 2, 15, 300, 0, NOW()),

('todos', '00001', 'BOLETO_30_45_60', 'Boleto 30/45/60', 3, 15, 450, 0, NOW()),
('todos', '00003', 'BOLETO_30_45_60', 'Boleto 30/45/60', 3, 15, 450, 0, NOW()),

('todos', '00001', 'BOLETO_30_60', 'Boleto 30/60', 2, 30, 500, 0, NOW()),
('todos', '00003', 'BOLETO_30_60', 'Boleto 30/60', 2, 30, 500, 0, NOW()),

('todos', '00001', 'BOLETO_30_60_90', 'Boleto 30/60/90', 3, 30, 900, 0, NOW()),
('todos', '00003', 'BOLETO_30_60_90', 'Boleto 30/60/90', 3, 30, 900, 0, NOW())
ON CONFLICT (cliente_codigo, loja_codigo, plano_codigo)
DO UPDATE SET
    plano_descricao = EXCLUDED.plano_descricao,
    parcelas = EXCLUDED.parcelas,
    dias_entre_parcelas = EXCLUDED.dias_entre_parcelas,
    valor_minimo = EXCLUDED.valor_minimo,
    valor_acrescimo = EXCLUDED.valor_acrescimo;
