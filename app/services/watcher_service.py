"""
Inbox-Watcher: Prüft den Inbox-Ordner zyklisch auf neue Dateien und startet
den Import automatisch.

Stabilitätsprüfung (verhindert Import laufender Kopiervorgänge):
  1. mtime-Alter: Die Datei muss mindestens `stability_threshold_seconds`
     Sekunden unverändert sein.
  2. Exklusiver Öffnungsversuch: Schlägt unter Windows fehl, wenn die Datei
     noch von einem anderen Prozess zum Schreiben geöffnet (gesperrt) ist.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from app.config import Config
from app.services import ingestion_service

logger = logging.getLogger(__name__)

_watcher_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# Stabilitätsprüfung
# ---------------------------------------------------------------------------

def is_file_stable(path: Path, min_age_seconds: float = 30.0) -> bool:
    """Gibt True zurück, wenn die Datei vollständig geschrieben zu sein scheint.

    Strategie:
    - mtime-Prüfung: Letzte Änderung muss mindestens *min_age_seconds* her sein.
    - Exklusiver Öffnungsversuch: Schlägt fehl, wenn die Datei noch von einem
      anderen Prozess zum Schreiben gesperrt ist (besonders relevant unter Windows).
    """
    try:
        stat = path.stat()
        age = time.time() - stat.st_mtime
        if age < min_age_seconds:
            return False
        # Sekundärcheck: Datei lesend öffnen – schlägt fehl bei aktiver Schreibsperre
        with open(path, "rb"):
            pass
        return True
    except (OSError, PermissionError):
        return False


# ---------------------------------------------------------------------------
# Hintergrundverarbeitung (analog zu routes_files._process_in_background)
# ---------------------------------------------------------------------------

def _process_in_background(file_id: str) -> None:
    """Verarbeitet eine importierte Datei in einem eigenen DB-Thread."""
    from app.db.database import _SessionLocal
    if _SessionLocal is None:
        logger.error("Watcher: _process_in_background – Datenbank nicht initialisiert.")
        return
    db = _SessionLocal()
    try:
        ingestion_service.process_file(file_id, db)
    except Exception:
        logger.exception("Watcher: Fehler bei der Verarbeitung von Datei %s.", file_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Scan-Zyklus
# ---------------------------------------------------------------------------

async def _scan_and_import(cfg: Config) -> None:
    """Führt einen einzelnen Scan-Zyklus durch: Inbox prüfen → importieren → verarbeiten."""
    from app.db.database import _SessionLocal

    files = ingestion_service.scan_inbox(cfg.paths.inbox)
    if not files:
        return

    threshold = cfg.watcher.stability_threshold_seconds
    stable = [f for f in files if is_file_stable(f, threshold)]
    unstable_count = len(files) - len(stable)

    if unstable_count:
        logger.debug(
            "Watcher: %d Datei(en) noch nicht stabil (mtime < %ds) – "
            "werden beim nächsten Scan erneut geprüft.",
            unstable_count,
            threshold,
        )

    if not stable:
        return

    logger.info("Watcher: %d stabile Datei(en) gefunden, starte Import.", len(stable))

    if _SessionLocal is None:
        logger.error("Watcher: Datenbank nicht initialisiert – Import übersprungen.")
        return

    imported_ids: list[str] = []
    db = _SessionLocal()
    try:
        for file_path in stable:
            try:
                result = ingestion_service.import_file(file_path, db, cfg.paths.archive_root)
                if result["status"] == "imported":
                    imported_ids.append(result["file_id"])
                    logger.info("Watcher: Importiert – %s", file_path.name)
                elif result["status"] == "duplicate":
                    logger.debug("Watcher: Duplikat übersprungen – %s", file_path.name)
            except Exception:
                logger.exception("Watcher: Fehler beim Import von '%s'.", file_path.name)
    finally:
        db.close()

    # Verarbeitung (OCR, Embedding …) asynchron in Thread-Pool starten
    for file_id in imported_ids:
        asyncio.create_task(asyncio.to_thread(_process_in_background, file_id))

    if imported_ids:
        logger.info(
            "Watcher: %d Datei(en) in die Verarbeitungswarteschlange eingereiht.",
            len(imported_ids),
        )


# ---------------------------------------------------------------------------
# Watcher-Schleife
# ---------------------------------------------------------------------------

async def _watcher_loop(cfg: Config) -> None:
    interval = cfg.watcher.scan_interval_seconds
    threshold = cfg.watcher.stability_threshold_seconds
    logger.info(
        "Inbox-Watcher gestartet – Scan-Intervall: %ds, Stabilitätsschwelle: %ds.",
        interval,
        threshold,
    )

    while True:
        try:
            await asyncio.sleep(interval)
            await _scan_and_import(cfg)
        except asyncio.CancelledError:
            logger.info("Inbox-Watcher wird beendet.")
            raise
        except Exception:
            logger.exception(
                "Watcher: Unerwarteter Fehler – nächster Scan in %ds.", interval
            )


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def start_watcher(cfg: Config) -> None:
    """Startet den Inbox-Watcher als asyncio-Task."""
    global _watcher_task
    _watcher_task = asyncio.create_task(_watcher_loop(cfg))


def stop_watcher() -> None:
    """Stoppt den Inbox-Watcher (wird beim App-Shutdown aufgerufen)."""
    global _watcher_task
    if _watcher_task and not _watcher_task.done():
        _watcher_task.cancel()
    _watcher_task = None
