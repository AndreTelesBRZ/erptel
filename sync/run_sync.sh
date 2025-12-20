#!/bin/bash

# Ativar o MESMO ambiente virtual que você usa manualmente
source /home/ubuntu/apps/Django/venv/bin/activate

# Ir para a pasta do script
cd /home/ubuntu/apps/Django/sync

# Executar a sincronização de PRODUTOS e gravar log
python3 sync_produtos.py >> /home/ubuntu/apps/Django/sync/sync.log 2>&1

# Executar a sincronização de CLIENTES e gravar log
python3 sync_clientes.py >> /home/ubuntu/apps/Django/sync/sync.log 2>&1
