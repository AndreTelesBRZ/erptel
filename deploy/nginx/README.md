# Nginx HTTPS para a API (porta 9000)

Este setup termina TLS no Nginx e encaminha:

- Django (`/`) -> `http://127.0.0.1:8000`
- FastAPI (`/auth` e `/api`) -> `http://127.0.0.1:9000`

## Passos (host Linux)

1) Copie o arquivo de configuração:

```sh
sudo mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
sudo cp /home/ubuntu/apps/Django/deploy/nginx/erp_api.conf /etc/nginx/sites-available/erp_api.conf
sudo ln -sf /etc/nginx/sites-available/erp_api.conf /etc/nginx/sites-enabled/erp_api.conf
```

2) Crie o webroot do certbot e ajuste permissões:

```sh
sudo mkdir -p /var/www/certbot
sudo chown -R www-data:www-data /var/www/certbot
```

3) Teste e recarregue o Nginx:

```sh
sudo nginx -t
sudo systemctl reload nginx
```

4) Emita o certificado (Let's Encrypt):

```sh
sudo certbot certonly --webroot -w /var/www/certbot -d erp.edsondosparafusos.app.br
```

5) Recarregue o Nginx novamente:

```sh
sudo systemctl reload nginx
```

## Observações

- Se a API estiver em outro host/porta, ajuste o `proxy_pass` em `erp_api.conf`.
- Este config usa `/api` para FastAPI. Se você precisar do `/api` do Django, será necessário alterar o prefixo da FastAPI (ex.: `/erp-api`).
- Se você quiser HTTPS para IP (sem domínio), será necessário um certificado autoassinado.

## HTTPS por IP (autoassinado)

1) Gere o certificado autoassinado:

```sh
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout /etc/nginx/ssl/erp_api_ip.key \
  -out /etc/nginx/ssl/erp_api_ip.crt \
  -subj "/CN=10.0.0.78"
```

2) Instale e habilite a configuração do IP:

```sh
sudo cp /home/ubuntu/apps/Django/deploy/nginx/erp_api_ip.conf /etc/nginx/sites-available/erp_api_ip.conf
sudo ln -sf /etc/nginx/sites-available/erp_api_ip.conf /etc/nginx/sites-enabled/erp_api_ip.conf
```

3) Teste e recarregue o Nginx:

```sh
sudo nginx -t
sudo systemctl reload nginx
```

4) Acesse via `https://10.0.0.78` (o navegador vai avisar por ser autoassinado).
