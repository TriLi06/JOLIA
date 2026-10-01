"""
Generischer Idle-Unload-Manager für lokal (im JOLIA-Prozess) geladene Modelle
(SentenceTransformer, OpenCLIP, CLAP, ...).

Diese Modelle werden bereits lazy beim ersten Gebrauch geladen (siehe die
jeweiligen *_service.py), aber ohne dieses Modul nie wieder freigegeben -
JOLIA läuft üblicherweise dauerhaft im Hintergrund, Importe/Chat-Anfragen
sind aber selten, sodass die Modelle die meiste Zeit ungenutzt Speicher
belegen würden.

Verwendung:
    model_lifecycle.register("embedding_model", _unload_fn)
    ...
    model_lifecycle.touch("embedding_model", idle_minutes=10.0)  # nach jeder Nutzung

Nach `idle_minutes` ohne erneuten touch()-Aufruf wird `_unload_fn` in einem
Timer-Thread ausgeführt und das Modell so aus dem Speicher entfernt.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    unload_fn: Callable[[], None]
    timer: threading.Timer | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_entries: dict[str, _Entry] = {}
_registry_lock = threading.Lock()


def register(name: str, unload_fn: Callable[[], None]) -> None:
    """Registriert ein Modell einmalig mit seiner Entlade-Funktion (idempotent)."""
    with _registry_lock:
        if name not in _entries:
            _entries[name] = _Entry(unload_fn=unload_fn)


def touch(name: str, idle_minutes: float) -> None:
    """Setzt den Idle-Timer für ein Modell zurück; muss nach jeder Nutzung aufgerufen werden."""
    entry = _entries.get(name)
    if entry is None:
        return
    with entry.lock:
        if entry.timer is not None:
            entry.timer.cancel()
            entry.timer = None
        if idle_minutes <= 0:
            return
        timer = threading.Timer(idle_minutes * 60.0, _unload, args=(name,))
        timer.daemon = True
        entry.timer = timer
        timer.start()


def _unload(name: str) -> None:
    entry = _entries.get(name)
    if entry is None:
        return
    with entry.lock:
        entry.timer = None
        try:
            entry.unload_fn()
            logger.info("Modell '%s' nach Leerlauf aus dem Speicher entladen.", name)
        except Exception:
            logger.exception("Entladen von Modell '%s' fehlgeschlagen.", name)


def unload_all() -> None:
    """Entlädt alle registrierten Modelle sofort (z.B. beim Shutdown)."""
    for name in list(_entries.keys()):
        _unload(name)


def gc_cleanup() -> None:
    """Räumt nach dem Entladen eines Modells Python- und (falls vorhanden) CUDA-Speicher auf."""
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
