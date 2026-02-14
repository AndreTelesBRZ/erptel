import psycopg2
from django.contrib.auth.models import User
from django.conf import settings
import hashlib

class ERPAuthBackend:
    def authenticate(self, request, username=None, password=None):
        conn = psycopg2.connect(settings.DATABASE_URL)
        cur = conn.cursor()

        # EXEMPLO — AJUSTE PARA SUA TABELA REAL
        cur.execute("""
            SELECT usuario, senha_hash
            FROM erp_usuarios
            WHERE usuario = %s AND ativo = true
        """, (username,))

        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return None

        senha_hash = row[1]

        if hashlib.sha256(password.encode()).hexdigest() == senha_hash:
            # cria usuário "fantasma" no Django (sem senha)
            user, _ = User.objects.get_or_create(username=username)
            return user

        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
