import secrets
import textwrap

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Gera um token aleatório para definir o APP_INTEGRATION_TOKEN em .env.edson "
        "ou .env.llfix."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            choices=("edson", "llfix"),
            default="edson",
            help="Tenant alvo do token (edson ou llfix)",
        )

    def handle(self, *args, **options):
        tenant = options["tenant"]
        token = secrets.token_urlsafe(64)
        env_file = ".env.edson" if tenant == "edson" else ".env.llfix"
        self.stdout.write(
            textwrap.dedent(
                f"""
                Token gerado para {tenant} ({env_file}):
                {token}

                Cole esse valor na variável APP_INTEGRATION_TOKEN de {env_file} e reinicie o serviço:
                    sudo systemctl daemon-reload
                    sudo systemctl restart erp-api.service apiforce_edson.service apiforce_llfix.service
                """
            ).strip()
        )
