from django.apps import AppConfig


class ProductsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'products'

    def ready(self):
        # Start background job que espelha o catálogo externo a cada 3 minutos.
        try:
            from .sync_scheduler import start_product_sync_scheduler
            start_product_sync_scheduler()
        except Exception as exc:  # pragma: no cover - evita quebrar inicialização
            import logging
            logging.getLogger(__name__).exception('Falha ao iniciar o agendador de produtos: %s', exc)
