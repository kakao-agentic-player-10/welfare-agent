from __future__ import annotations

from datetime import datetime, timedelta
import logging
import threading
from zoneinfo import ZoneInfo

from welfare_agent.config import Settings
from welfare_agent.ingestion.enrichment import (
    enrich_public_service_conditions,
    enrichment_options_from_settings,
)
from welfare_agent.ingestion.sync import options_from_settings, sync_benefits


logger = logging.getLogger(__name__)
_scheduler: BackgroundSyncScheduler | None = None
_scheduler_lock = threading.Lock()


class BackgroundSyncScheduler:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="welfare-sync-scheduler",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run_loop(self) -> None:
        if self.settings.sync_on_startup:
            self._run_once("startup")

        while self.settings.sync_daily and not self._stop.is_set():
            seconds = seconds_until_next_run(
                timezone_name=self.settings.sync_timezone,
                hour=self.settings.sync_hour,
                minute=self.settings.sync_minute,
            )
            if self._stop.wait(seconds):
                break
            self._run_once("daily")

    def _run_once(self, reason: str) -> None:
        try:
            logger.info("welfare sync started: %s", reason)
            sync_benefits(self.settings, options_from_settings(self.settings), log=logger.info)
            logger.info("supportConditions enrichment started: %s", reason)
            enrich_public_service_conditions(
                self.settings,
                enrichment_options_from_settings(self.settings),
                log=logger.info,
            )
            logger.info("welfare sync finished: %s", reason)
        except Exception:
            logger.exception("welfare sync failed: %s", reason)


def start_background_sync(settings: Settings) -> BackgroundSyncScheduler | None:
    global _scheduler
    if not settings.sync_enabled:
        return None

    with _scheduler_lock:
        if _scheduler is not None:
            return _scheduler
        _scheduler = BackgroundSyncScheduler(settings)
        _scheduler.start()
        return _scheduler


def seconds_until_next_run(*, timezone_name: str, hour: int, minute: int) -> float:
    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()
