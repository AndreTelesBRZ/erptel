import logging
import os
import sys
import threading
import time
from typing import Any

from django.db import close_old_connections

from .utils import mirror_products_from_sync

logger = logging.getLogger(__name__)

_scheduler_started = False
_run_lock = threading.Lock()


def _should_start_scheduler() -> bool:
	"""
	Decide if the background scheduler should start.
	Skips heavy management commands (migrate/test/etc) and respects env toggles.
	"""
	def _log_skip(reason: str) -> None:
		logger.info('product-sync: scheduler não iniciado (%s).', reason)

	if os.getenv('PRODUCT_SYNC_DISABLED', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
		_log_skip('PRODUCT_SYNC_DISABLED ativo')
		return False

	argv = sys.argv
	reloader_flag = (os.getenv('DJANGO_AUTORELOAD_ENV') or os.getenv('RUN_MAIN') or '').strip().lower()
	is_noreload = any(arg in {'--noreload', '--no-reload'} for arg in argv)

	def _should_skip_runserver(cmd: str) -> bool:
		"""
		Django 5 usa DJANGO_AUTORELOAD_ENV na criança do reloader (ex.: 'statreload');
		RUN_MAIN pode não existir. Qualquer valor indica que já estamos no processo filho
		e podemos iniciar com segurança. Com --noreload há só um processo.
		"""
		if cmd != 'runserver':
			return False
		if reloader_flag or is_noreload:
			return False
		# Avoid starting the scheduler twice with Django's auto-reloader
		return True

	if len(argv) >= 2:
		command = argv[1]
		if command in {'migrate', 'makemigrations', 'collectstatic', 'shell', 'test', 'loaddata', 'dumpdata'}:
			_log_skip(f'ignorado para comando {command}')
			return False
		if _should_skip_runserver(command):
			_log_skip('aguardando processo filho do autoreload do runserver')
			return False
	return True


def _interval_seconds() -> int:
	try:
		return max(60, int(os.getenv('PRODUCT_SYNC_INTERVAL_SECONDS', '180')))
	except (TypeError, ValueError):
		return 180


def _run_sync_cycle() -> None:
	if _run_lock.locked():
		logger.info('product-sync: previous cycle still running, skipping this interval.')
		return

	with _run_lock:
		close_old_connections()
		try:
			result: dict[str, Any] = mirror_products_from_sync(update=True)
			logger.info(
				'product-sync: concluído (processados=%s, criados=%s, atualizados=%s, existentes=%s, ignorados=%s).',
				result.get('processed'),
				result.get('created'),
				result.get('updated'),
				result.get('existing'),
				result.get('invalid'),
			)
		except Exception:
			logger.exception('product-sync: falha ao espelhar catálogo externo.')
		finally:
			close_old_connections()


def _worker(interval: int) -> None:
	logger.info('product-sync: scheduler iniciado (intervalo=%ss).', interval)
	while True:
		_run_sync_cycle()
		time.sleep(interval)


def start_product_sync_scheduler() -> None:
	"""Public entry to start the scheduler (called from AppConfig.ready)."""
	global _scheduler_started
	if _scheduler_started:
		return
	if not _should_start_scheduler():
		return

	interval = _interval_seconds()
	thread = threading.Thread(
		target=_worker,
		args=(interval,),
		name='product-sync-scheduler',
		daemon=True,
	)
	thread.start()
	_scheduler_started = True
