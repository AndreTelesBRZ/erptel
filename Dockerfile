FROM python:3.12-slim

# Variáveis básicas para um container previsível
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# Dependências do sistema necessárias para build de libs (pyodbc, psycopg2, Pillow)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       libpq-dev \
       unixodbc-dev \
       gcc \
       g++ \
       libjpeg-dev \
       zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Instalação das dependências Python
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Copia o código do projeto
COPY . .

# Porta exposta pelo Django/Gunicorn
EXPOSE 8000

# Comando padrão: servidor WSGI
CMD ["gunicorn", "mysite.wsgi:application", "--bind", "0.0.0.0:8000"]
