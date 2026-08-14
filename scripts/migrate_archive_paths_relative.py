"""Einmalige Migration: archive_path in der DB von absolut auf relativ (zu archive_root) umstellen.

Grund: Bisher wurde der volle absolute Pfad gespeichert. Wird der Archiv-Root-Ordner
umbenannt oder verschoben (z.B. "docstoreai-test" -> "jolia-test"), verweisen bereits
importierte Dateien dann ins Leere ("Archivdatei nicht gefunden").

Ab sofort speichert die App relative Pfade (relativ zu paths.archive_root aus der
config.yaml). Dieses Skript rechnet bestehende absolute Einträge einmalig um, indem es
die letzten 4 Pfadteile (content_type/YYYY/MM/<uuid>.<ext>, siehe
app.services.archive_service.calculate_archive_path) übernimmt.

Aufruf:  python scripts/migrate_archive_paths_relative.py [--config config.yaml] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config
from app.db import database
from app.db.models import File


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nichts schreiben")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    database.init_db(cfg.paths.data_dir / "archive.db")

    archive_root = cfg.paths.archive_root
    updated = 0
    missing = 0
    already_relative = 0

    db = database._SessionLocal()
    try:
        files = db.query(File).all()
        for f in files:
            p = Path(f.archive_path)
            if not p.is_absolute():
                already_relative += 1
                continue

            # Struktur: .../<content_type>/<YYYY>/<MM>/<uuid><ext>
            rel = Path(*p.parts[-4:])
            resolved = archive_root / rel
            if not resolved.exists():
                print(f"WARNUNG: Datei nicht gefunden, überspringe: {f.original_filename} -> {resolved}")
                missing += 1
                continue

            print(f"{f.archive_path}  ->  {rel}")
            if not args.dry_run:
                f.archive_path = str(rel)
                updated += 1

        if not args.dry_run and updated:
            db.commit()
    finally:
        db.close()

    print(f"\nFertig. Aktualisiert: {updated}, bereits relativ: {already_relative}, nicht gefunden: {missing}")
    if args.dry_run:
        print("(--dry-run: keine Änderungen gespeichert)")


if __name__ == "__main__":
    main()
