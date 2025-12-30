# Projeto Django (PT-BR)

Projeto Django criado para fins de desenvolvimento com as aplicações de Produtos e Clientes.

Como usar (Linux):

1. Ativar o ambiente virtual:

```sh
. .venv/bin/activate
```

2. Instalar dependências (se você não tiver o `.venv`):

```sh
pip install -r requirements.txt
```

3. Rodar migrações e iniciar o servidor:

```sh
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

4. Acesse no navegador:

- Login / Início: http://localhost:8000/
- Dashboard (após login): http://localhost:8000/dashboard/
- Admin: http://localhost:8000/admin/

Usuário de teste criado: `Andre` (use a senha que você forneceu durante a criação do superuser)

Observações:
- As rotas de criação/edição/exclusão e exportação CSV requerem autenticação.
- Ajuste a porta no comando `runserver` caso prefira outra porta disponível.

## Rodar com Docker / Containers

Arquivos incluídos:
- `Dockerfile`: imagem Python 3.12‑slim com Gunicorn.
- `docker-compose.yml`: sobe `web` (Django) e `db` (Postgres 16).
- `.env.example`: modelo das variáveis.

Passo a passo:
1. Copie o exemplo de ambiente e ajuste as variáveis (SECRET_KEY, POSTGRES_*, etc.):
   ```sh
   cp .env.example .env
   ```
2. Suba os containers:
   ```sh
   docker compose up -d --build
   ```
3. Aplique migrações e crie um usuário admin (executa dentro do container `web`):
   ```sh
   docker compose exec web python manage.py migrate
   docker compose exec web python manage.py createsuperuser
   ```
4. Acesse em http://localhost:8000/ (porta configurável no `docker-compose.yml`).

Notas rápidas:
- O volume `postgres_data` persiste o banco; `media_data` persiste uploads.
- O serviço `web` já está conectado no Postgres interno (`POSTGRES_HOST=db`).
- Para acompanhar logs: `docker compose logs -f web` ou `docker compose logs -f db`.

## Deploy rápido em outra máquina (Tailscale/SSH)

Pré‑requisitos na máquina remota:
- Linux com `python3`/`venv`, `ssh` e `rsync` instalados
- Acesso por SSH (ex.: `user@100.x.y.z` da sua rede Tailscale)
- Postgres acessível (edite `.env` no remoto para `POSTGRES_*` e inclua o host em `ALLOWED_HOSTS`)

Comandos úteis:
- Copiar e subir o projeto no remoto (padrão porta 8000):
  `scripts/remote_deploy.sh user@host --dest "~/apps/Django" --port 8000 --copy-env`
- Ver status/logs no remoto:
  `scripts/remote_status.sh user@host --dest "~/apps/Django"`
- Parar o servidor no remoto:
  `scripts/remote_stop.sh user@host --dest "~/apps/Django"`

Usando Tailscale SSH (sem abrir porta 22):
- Se você habilitou `tailscale up --ssh` no remoto, pode usar os scripts desta forma:
  ```sh
  SSH_BIN="tailscale ssh" scripts/remote_deploy.sh ubuntu@100.93.x.y --dest "~/apps/Django" --port 8000 --copy-env
  SSH_BIN="tailscale ssh" scripts/remote_status.sh ubuntu@100.93.x.y --dest "~/apps/Django"
  SSH_BIN="tailscale ssh" scripts/remote_stop.sh ubuntu@100.93.x.y --dest "~/apps/Django"
  ```
  Substitua `ubuntu` pelo usuário que existe no remoto.

Notas:
- O deploy usa `rsync` (exclui `.venv`, `.git`, backups), cria `.venv`, instala `requirements.txt`, roda `migrate` e inicia `runserver` em background (nohup).
- Se não quiser expor a porta, use túnel: `ssh -L 8000:127.0.0.1:8000 user@host` e acesse http://localhost:8000.

### Rodar como serviço (systemd)

ATENÇÃO: isto usa o servidor de desenvolvimento do Django (runserver), adequado para ambiente interno/VPN. Para produção, use Gunicorn/Uvicorn + Nginx.

Instalar/habilitar o serviço no remoto:

```sh
scripts/remote_systemd_install.sh user@host \
  --dest ~/apps/Django \
  --port 8000 \
  --service django-erp   # opcional
```

Comandos úteis no remoto:

```sh
sudo systemctl status django-erp
sudo journalctl -u django-erp -f
sudo systemctl restart django-erp
```

Remover o serviço:

```sh
scripts/remote_systemd_remove.sh user@host --service django-erp
```

Também é possível pedir ao deploy para já instalar o serviço:

```sh
scripts/remote_deploy.sh user@host --dest ~/apps/Django --port 8000 --copy-env --systemd --service django-erp
```

## Exportar e importar produtos

- No menu **Produtos**, use o botão `Exportar CSV` para baixar a planilha `produtos_export.csv`. O arquivo usa ponto e vírgula (`;`) como separador e contém todas as colunas utilizadas pelo importador.
- Para atualizar ou incluir itens a partir desse arquivo, edite as linhas desejadas e depois acesse **Produtos → Importar CSV** (requer usuário staff). O importador respeita códigos já existentes e cria novos registros quando o código não é encontrado.
- Caso precise ajustar o mapeamento das colunas de um CSV diferente, utilize **Importar com mapeamento** para combinar manualmente os campos ou rode `python manage.py import_products_csv <arquivo>` na linha de comando.

## Banco de Dados PostgreSQL (busca otimizada)

Este projeto usa SQLite por padrão. Para ativar PostgreSQL com busca otimizada (pg_trgm):

1) Crie um arquivo `.env` (existe um exemplo):

```sh
cp .env.example .env
```

Edite `.env` e ajuste as variáveis (SECRET_KEY, DB_ENGINE, POSTGRES_*). Em alternativa, você pode usar `DATABASE_URL` com `django-environ` (opcional; `pip install django-environ`). Em seguida, instale as dependências:

```sh
export DB_ENGINE=postgres
export POSTGRES_DB=meubanco
export POSTGRES_USER=meuuser
export POSTGRES_PASSWORD=senh@segura
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=5432
pip install -r requirements.txt

Ou, usando `DATABASE_URL`:

```sh
pip install django-environ
export DATABASE_URL='postgres://meuuser:senh@segura@127.0.0.1:5432/meubanco'
```
```

## API de integração de pedidos de venda

- Autenticação: header `X-App-Token: <seu_token>` onde `<seu_token>` vem de `APP_INTEGRATION_TOKEN` no `.env` (se não definir, fica liberado – defina em produção).
- Criar pedido: `POST /api/pedidos-venda/` (ou `/api/pedidos` para compatibilidade) com payload:

```json
{
  "data_criacao": "2025-01-15T10:30:00-03:00",
  "total": "20.00",
  "cliente_id": 1,
  "itens": [
    { "codigo_produto": 10, "quantidade": "2", "valor_unitario": "10.00" }
  ]
}
```

- Listar pedidos recebidos: `GET /api/pedidos-venda/?recebido_depois=2025-01-01T00:00:00-03:00` (paginado). Também aceita `cliente_id`, `cliente_codigo`, `recebido_ate`, `criado_depois` e `criado_ate`.
- Detalhe: `GET /api/pedidos-venda/<id>/` retorna dados do cliente e itens com subtotal.

## Sincronização de inadimplência

A sincronização de inadimplência roda como tarefa em background no Django.

Variáveis de ambiente suportadas:
- `INADIMPLENCIA_SYNC_TIMES`: horários (HH:MM) separados por vírgula. Ex.: `09:00,15:00` (padrão).
- `INADIMPLENCIA_SYNC_DISABLED`: `true` para desabilitar o agendador.
- `SQLSERVER_HOST`: host do SQL Server (padrão `10.0.0.60`).
- `SQLSERVER_PORT`: porta do SQL Server (padrão `1433`).
- `SQLSERVER_DB`: banco do SQL Server (padrão `SysacME`).
- `SQLSERVER_USER`: usuário (padrão `sync_erptel`).
- `SQLSERVER_PASSWORD`: senha (padrão `SenhaForte@2025`).
- `SQLSERVER_ENCRYPT`: `yes`/`no` (padrão `yes`).
- `SQLSERVER_TRUST_CERT`: `yes`/`no` (padrão `yes`).

2) Migre os dados do SQLite para Postgres

Opção A (script automatizado):

```sh
./scripts/to_postgres.sh
```

O script faz:
- dump do SQLite (forçando `DB_ENGINE=sqlite` na chamada do `dumpdata`),
- `migrate` usando sua configuração Postgres do `.env`,
- `loaddata` do dump gerado e `check_search` para garantir `pg_trgm`/índices.

Opção B (manual):

```sh
# 1) Antes de habilitar o .env, exporte os dados do SQLite
DB_ENGINE=sqlite python manage.py dumpdata \
  --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission --exclude admin.logentry \
  --indent 2 > backup.json

# 2) Habilite Postgres (edite .env conforme acima) e aplique migrações
python manage.py migrate

# 3) Importe os dados
python manage.py loaddata backup.json
```

3) Aplique migrações (criam a extensão e índices trgm quando em Postgres):

```sh
python manage.py migrate
```

4) (Opcional) Verifique extensão/índices e tente criar pg_trgm automaticamente:

```sh
python manage.py check_search
```

Observação: em Postgres, a busca aceita curingas ordenados (`par%franc%x3`) e ordena por similaridade (trigram). Em SQLite, o comportamento é compatível (AND dos pedaços), porém sem ordenação por similaridade.

## Sincronizar produtos (SQL Server → Postgres)

- Garanta o driver ODBC do SQL Server instalado no Ubuntu (Driver 18): `sudo /opt/microsoft/msodbcsql18/bin/mssql-conf verify` ou instale conforme docs da Microsoft.
- Preencha `.env` com as variáveis `MSSQL_HOST/PORT/DB/USER/PASSWORD` e, se usar o driver 18, mantenha `MSSQL_TRUST_CERT=yes` (o padrão `MSSQL_DRIVER="ODBC Driver 18 for SQL Server"` já está no arquivo).
- Rode as migrações para criar a tabela de staging e a view consumida pelo Django: `python manage.py migrate products`.
- Execute a sincronização manual quando precisar: `python manage.py mirror_products_sync --chunk-size 1000`. Ela faz upsert em `erp_produtos_sync` e expõe os dados na view `vw_produtos_sync_preco_estoque` usada pelo app (a origem no SQL Server vem de `MSSQL_PRODUTOS_VIEWS`, lista separada por vírgulas).
- Para automatizar, agende no cron/systemd um job chamando o comando acima (ex.: a cada 15 minutos) e monitore o log de saída para eventuais falhas de conexão.
