"""
Generischer periodischer Job-Scheduler für Wartungsaufgaben (Face-/Location-/Duplikat-Clustering
als kombinierter Job, Backup). Analog zu watcher_service.py (asyncio-Loop), nutzt AppSetting als
Persistenz für last_run_at je Job, damit Zustand einen Neustart übersteht.

Der Clustering-Job läuft stündlich, aber nur wenn seit dem letzten Lauf tatsächlich neue Daten
verarbeitet wurden oder die App neu gestartet wurde (siehe mark_dirty()/_DIRTY_GATED_TASKS) -
ansonsten waere jede stuendliche Neuberechnung ueber den kompletten Datenbestand verschwendet.

Aktivierung/Intervalle in config.yaml unter scheduled_jobs:.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import Config, ScheduledJobConfig
from app.db import repositories as repo

logger = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None
TICK_SECONDS = 30


def _now() -> datetime:
    return datetime.now()


def _parse_last_run(raw: str) -> datetime:
    """Parst last_run_at, das aus alten (tz-aware UTC) oder neuen (naive lokale) Läufen stammen kann."""
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _run_rebuild_clustering(db: Session, cfg: Config) -> str:
    """Führt Gesichter-/Standort-Clustering und Duplikaterkennung nacheinander in einem Rutsch aus.

    Alle drei rechnen ohnehin ueber den kompletten Datenbestand neu (kein inkrementelles
    Update), daher werden sie hier zu einem einzigen periodischen Job zusammengefasst statt
    getrennt geplant.
    """
    from app.services import duplicate_service, face_service, location_service

    faces_result = face_service.rebuild_person_clusters(db)
    locations_result = location_service.rebuild_location_clusters(db)
    duplicates_result = duplicate_service.rebuild_duplicate_groups(
        db,
        hash_threshold=cfg.processing.duplicate_hash_threshold,
        time_window_seconds=cfg.processing.duplicate_time_window_seconds,
    )
    return (
        f"Gesichter: {faces_result} | Standorte: {locations_result} | Duplikate: {duplicates_result}"
    )


def _run_backup(db: Session, cfg: Config) -> str:
    from app.services import backup_service
    record = repo.create_backup_record(db, str(cfg.paths.backup_target))
    try:
        files_copied, bytes_copied, log = backup_service.run_backup(
            cfg.paths.archive_root, cfg.paths.data_dir, cfg.paths.backup_target
        )
        repo.finish_backup(db, record.id, success=True, files_copied=files_copied, bytes_copied=bytes_copied)
        return log
    except Exception as exc:
        repo.finish_backup(db, record.id, success=False, error_message=str(exc))
        raise


# name -> (Anzeigename, Config-Feld unter scheduled_jobs, Ausführungsfunktion)
TASK_REGISTRY: dict[str, dict] = {
    "rebuild_clustering": {
        "label": "Gesichter-/Standort-Clustering & Duplikaterkennung",
        "config_key": "clustering",
        "run": _run_rebuild_clustering,
    },
    "backup": {"label": "Backup", "config_key": "backup", "run": _run_backup},
}

# Jobs, die nur laufen sollen, wenn seit dem letzten Lauf neue Daten verarbeitet wurden
# oder die App neu gestartet wurde (siehe mark_dirty()).
_DIRTY_GATED_TASKS = {"rebuild_clustering"}


def mark_dirty(db: Session, task_name: str = "rebuild_clustering") -> None:
    """Markiert einen dirty-gated Job als 'es gibt neue Daten' (nach Import oder App-Start)."""
    repo.set_setting(db, f"dirty:{task_name}", "1")


def _job_config(cfg: Config, config_key: str) -> ScheduledJobConfig:
    return getattr(cfg.scheduled_jobs, config_key)


def run_task_now(name: str, db: Session, cfg: Config) -> None:
    """Führt einen registrierten Wartungsjob sofort aus (manuell oder vom Scheduler-Tick)."""
    task = TASK_REGISTRY.get(name)
    if not task:
        raise ValueError(f"Unbekannter Job: {name}")
    job = repo.create_job(db, file_id=None, job_type=name)
    repo.start_job(db, job.id)
    try:
        log = task["run"](db, cfg)
        repo.finish_job(db, job.id, success=True, log=str(log)[:2000])
    except Exception as exc:
        logger.exception("Geplanter Job '%s' fehlgeschlagen", name)
        repo.finish_job(db, job.id, success=False, error_message=str(exc))
    finally:
        repo.set_setting(db, f"last_run:{name}", _now().isoformat())


def get_schedule_status(db: Session, cfg: Config) -> list[dict]:
    """Liefert Anzeigedaten (Intervall, letzte/nächste Ausführung, fällig/überfällig) je Job."""
    statuses = []
    for name, task in TASK_REGISTRY.items():
        job_cfg = _job_config(cfg, task["config_key"])
        last_run_raw = repo.get_setting(db, f"last_run:{name}")
        next_due_at = None
        is_due = True
        is_overdue = False
        if last_run_raw:
            last_run = _parse_last_run(last_run_raw)
            next_due_ts = last_run.timestamp() + job_cfg.interval_seconds
            now_ts = _now().timestamp()
            is_due = now_ts >= next_due_ts
            # Überfällig = mehr als ein weiteres volles Intervall verstrichen (Kulanzfenster)
            is_overdue = now_ts >= next_due_ts + job_cfg.interval_seconds
            next_due_at = datetime.fromtimestamp(next_due_ts).isoformat()
        statuses.append({
            "name": name,
            "label": task["label"],
            "enabled": job_cfg.enabled,
            "interval_seconds": job_cfg.interval_seconds,
            "last_run_at": last_run_raw,
            "next_due_at": next_due_at,
            "is_due": is_due,
            "is_overdue": is_overdue,
        })
    return statuses


async def _scheduler_tick(cfg: Config) -> None:
    from app.db.database import _SessionLocal
    if _SessionLocal is None:
        return
    db = _SessionLocal()
    try:
        for name, task in TASK_REGISTRY.items():
            job_cfg = _job_config(cfg, task["config_key"])
            if not job_cfg.enabled:
                continue
            last_run_raw = repo.get_setting(db, f"last_run:{name}")
            due = True
            if last_run_raw:
                last_run = _parse_last_run(last_run_raw)
                due = (_now() - last_run).total_seconds() >= job_cfg.interval_seconds
            if due and name in _DIRTY_GATED_TASKS:
                due = repo.get_setting(db, f"dirty:{name}") == "1"
            if due:
                logger.info("Scheduler: starte periodischen Job '%s'.", name)
                await asyncio.to_thread(run_task_now, name, db, cfg)
                if name in _DIRTY_GATED_TASKS:
                    repo.set_setting(db, f"dirty:{name}", "0")
    finally:
        db.close()


async def _scheduler_loop(cfg: Config) -> None:
    logger.info("Job-Scheduler gestartet (Tick alle %ds).", TICK_SECONDS)
    while True:
        try:
            await asyncio.sleep(TICK_SECONDS)
            await _scheduler_tick(cfg)
        except asyncio.CancelledError:
            logger.info("Job-Scheduler wird beendet.")
            raise
        except Exception:
            logger.exception("Scheduler: Unerwarteter Fehler im Tick.")


def start_scheduler(cfg: Config) -> None:
    global _scheduler_task
    from app.db.database import _SessionLocal
    if _SessionLocal is not None:
        # App-Neustart zaehlt als "neue Daten koennten vorliegen" (z.B. nach Absturz waehrend
        # der Verarbeitung), daher den naechsten Tick fuer dirty-gated Jobs erzwingen.
        db = _SessionLocal()
        try:
            for name in _DIRTY_GATED_TASKS:
                mark_dirty(db, name)
        finally:
            db.close()
    _scheduler_task = asyncio.create_task(_scheduler_loop(cfg))


def stop_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task:
        _scheduler_task.cancel()
        _scheduler_task = None
