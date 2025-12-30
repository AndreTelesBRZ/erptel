import logging
import os
import sys
import threading
import time
from datetime import datetime, time as time_cls, timedelta

from django.utils import timezone as dj_timezone

logger = logging.getLogger(__name__)

_scheduler_started = False
_run_lock = threading.Lock()


def _should_start_scheduler() -> bool:
    """
    Decide if the background scheduler should start.
    Skips heavy management commands (migrate/test/etc) and respects env toggles.
    """
    def _log_skip(reason: str) -> None:
        logger.info('inadimplencia-sync: scheduler nao iniciado (%s).', reason)

    if os.getenv('INADIMPLENCIA_SYNC_DISABLED', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
        _log_skip('INADIMPLENCIA_SYNC_DISABLED ativo')
        return False

    argv = sys.argv
    reloader_flag = (os.getenv('DJANGO_AUTORELOAD_ENV') or os.getenv('RUN_MAIN') or '').strip().lower()
    is_noreload = any(arg in {'--noreload', '--no-reload'} for arg in argv)

    def _should_skip_runserver(cmd: str) -> bool:
        if cmd != 'runserver':
            return False
        if reloader_flag or is_noreload:
            return False
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


def _parse_sync_times() -> list[time_cls]:
    raw = os.getenv('INADIMPLENCIA_SYNC_TIMES', '09:00,15:00')
    times = []
    for chunk in raw.split(','):
        value = chunk.strip()
        if not value:
            continue
        try:
            hour_str, minute_str = value.split(':', 1)
            times.append(time_cls(int(hour_str), int(minute_str)))
        except ValueError:
            logger.warning('inadimplencia-sync: horario invalido ignorado: %s', value)
    return sorted(times)


def _now() -> datetime:
    try:
        return dj_timezone.localtime(dj_timezone.now())
    except Exception:
        return datetime.now()


def _next_run_at(now: datetime, times: list[time_cls]) -> datetime:
    if not times:
        return now
    today = now.date()
    candidates = [datetime.combine(today, t, tzinfo=now.tzinfo) for t in times]
    for candidate in candidates:
        if candidate >= now:
            return candidate
    return datetime.combine(today, times[0], tzinfo=now.tzinfo) + timedelta(days=1)


def _run_sync_cycle() -> None:
    if _run_lock.locked():
        logger.info('inadimplencia-sync: ciclo anterior ainda em execucao, pulando.')
        return
    with _run_lock:
        try:
            from sync.sync_inadimplencia import main
            main()
        except Exception:
            logger.exception('inadimplencia-sync: falha ao sincronizar inadimplencia.')


def _worker() -> None:
    times = _parse_sync_times()
    if not times:
        logger.warning('inadimplencia-sync: nenhum horario configurado, scheduler encerrado.')
        return
    logger.info('inadimplencia-sync: scheduler iniciado (horarios=%s).', ','.join(t.strftime('%H:%M') for t in times))
    while True:
        now = _now()
        next_run = _next_run_at(now, times)
        sleep_seconds = max(1, int((next_run - now).total_seconds()))
        time.sleep(sleep_seconds)
        _run_sync_cycle()


def start_inadimplencia_sync_scheduler() -> None:
    """Public entry to start the scheduler (called from AppConfig.ready)."""
    global _scheduler_started
    if _scheduler_started:
        return
    if not _should_start_scheduler():
        return
    thread = threading.Thread(
        target=_worker,
        name='inadimplencia-sync-scheduler',
        daemon=True,
    )
    thread.start()
    _scheduler_started = True
