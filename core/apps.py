import logging

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        try:
            from .inadimplencia_scheduler import start_inadimplencia_sync_scheduler
            start_inadimplencia_sync_scheduler()
        except Exception as exc:  # pragma: no cover - evita quebrar inicialização
            logging.getLogger(__name__).exception(
                'Falha ao iniciar o agendador de inadimplencia: %s',
                exc,
            )
