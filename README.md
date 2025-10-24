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
python manage.py runserver 127.0.0.1:8004
```

4. Acesse no navegador:

- Login / Início: http://127.0.0.1:8004/
- Dashboard (após login): http://127.0.0.1:8004/dashboard/
- Admin: http://127.0.0.1:8004/admin/

Usuário de teste criado: `Andre` (use a senha que você forneceu durante a criação do superuser)

Observações:
- As rotas de criação/edição/exclusão e exportação CSV requerem autenticação.
- Ajuste a porta no comando `runserver` caso prefira outra porta disponível.

## Deploy rápido em outra máquina (Tailscale/SSH)

Pré‑requisitos na máquina remota:
- Linux com `python3`/`venv`, `ssh` e `rsync` instalados
- Acesso por SSH (ex.: `user@100.x.y.z` da sua rede Tailscale)
- Postgres acessível (edite `.env` no remoto para `POSTGRES_*` e inclua o host em `ALLOWED_HOSTS`)

Comandos úteis:
- Copiar e subir o projeto no remoto (padrão porta 8020):
  `scripts/remote_deploy.sh user@host --dest "~/apps/Django" --port 8020 --copy-env`
- Ver status/logs no remoto:
  `scripts/remote_status.sh user@host --dest "~/apps/Django"`
- Parar o servidor no remoto:
  `scripts/remote_stop.sh user@host --dest "~/apps/Django"`

Usando Tailscale SSH (sem abrir porta 22):
- Se você habilitou `tailscale up --ssh` no remoto, pode usar os scripts desta forma:
  ```sh
  SSH_BIN="tailscale ssh" scripts/remote_deploy.sh ubuntu@100.93.x.y --dest "~/apps/Django" --port 8020 --copy-env
  SSH_BIN="tailscale ssh" scripts/remote_status.sh ubuntu@100.93.x.y --dest "~/apps/Django"
  SSH_BIN="tailscale ssh" scripts/remote_stop.sh ubuntu@100.93.x.y --dest "~/apps/Django"
  ```
  Substitua `ubuntu` pelo usuário que existe no remoto.

Notas:
- O deploy usa `rsync` (exclui `.venv`, `.git`, backups), cria `.venv`, instala `requirements.txt`, roda `migrate` e inicia `runserver` em background (nohup).
- Se não quiser expor a porta, use túnel: `ssh -L 8020:127.0.0.1:8020 user@host` e acesse http://localhost:8020.

### Rodar como serviço (systemd)

ATENÇÃO: isto usa o servidor de desenvolvimento do Django (runserver), adequado para ambiente interno/VPN. Para produção, use Gunicorn/Uvicorn + Nginx.

Instalar/habilitar o serviço no remoto:

```sh
scripts/remote_systemd_install.sh user@host \
  --dest ~/apps/Django \
  --port 8020 \
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
scripts/remote_deploy.sh user@host --dest ~/apps/Django --port 8020 --copy-env --systemd --service django-erp
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
# erptel
