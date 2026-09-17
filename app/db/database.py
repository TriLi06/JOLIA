from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_engine = None
_SessionLocal = None


class Base(DeclarativeBase):
    pass


def init_db(db_path: Path) -> None:
    global _engine, _SessionLocal

    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{db_path.as_posix()}"
    # Pool großzügig bemessen: Watcher/Uploads können mehrere Dateien parallel
    # verarbeiten, jede hält für die Dauer der Verarbeitung eine Session offen.
    _engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        pool_size=10,
        max_overflow=20,
        pool_timeout=60,
    )

    @event.listens_for(_engine, "connect")
    def set_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    # Modelle importieren damit Base die Tabellen kennt
    import app.db.models  # noqa: F401

    Base.metadata.create_all(_engine)

    # Schema-Migration: neue Spalten hinzufügen falls noch nicht vorhanden
    _migrate_schema(_engine)


def get_session() -> Generator[Session, None, None]:
    if _SessionLocal is None:
        raise RuntimeError("Datenbank nicht initialisiert. init_db() zuerst aufrufen.")
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_engine():
    return _engine


def _migrate_schema(engine) -> None:
    """Fügt neue Spalten zur files-Tabelle hinzu, falls noch nicht vorhanden (SQLite ALTER TABLE)."""
    _new_columns = {
        "files": [
            ("ai_summary", "TEXT"),
            ("thumbnail_path", "TEXT"),
            ("user_description", "TEXT"),
            ("perceptual_hash", "VARCHAR(32)"),
            ("sharpness_score", "FLOAT"),
            ("best_file_id", "VARCHAR(36)"),
            ("best_manually_set", "BOOLEAN NOT NULL DEFAULT 0"),
            ("category_id", "VARCHAR(36)"),
            ("category_assigned_by", "VARCHAR(16)"),
            ("category_needs_review", "BOOLEAN NOT NULL DEFAULT 0"),
            ("category_ai_response", "TEXT"),
            ("category_review_reason", "TEXT"),
        ]
    }
    with engine.connect() as conn:
        for table, columns in _new_columns.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}
            for col_name, col_type in columns:
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
