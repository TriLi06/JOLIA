from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now().isoformat()


class File(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    archive_path: Mapped[str] = mapped_column(Text, nullable=False)
    sidecar_json_path: Mapped[str | None] = mapped_column(Text)
    sidecar_md_path: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(128))
    content_type: Mapped[str | None] = mapped_column(String(32), index=True)  # Datei-Typ: documents/images/audio/video/other
    file_size: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[str | None] = mapped_column(String(32))
    imported_at: Mapped[str] = mapped_column(String(32), nullable=False, default=_now_iso)
    processed_at: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="imported", index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    ai_summary: Mapped[str | None] = mapped_column(Text)  # KI-generierte Kurzzusammenfassung (~300 Zeichen)
    thumbnail_path: Mapped[str | None] = mapped_column(Text)  # Relativer Pfad zum generierten Thumbnail
    user_description: Mapped[str | None] = mapped_column(Text)  # Manuelle Beschreibung durch den Benutzer
    perceptual_hash: Mapped[str | None] = mapped_column(String(32), index=True)  # pHash fuer Duplikat-/Serienerkennung
    sharpness_score: Mapped[float | None] = mapped_column(Float)  # Laplacian-Varianz (hoeher = schaerfer)
    best_file_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("files.id"), index=True
    )  # zeigt auf beste Aufnahme der Serie; None = ist selbst die beste bzw. keiner Serie zugeordnet
    best_manually_set: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # User hat Best-Auswahl ueberschrieben

    chunks: Mapped[list[Chunk]] = relationship(
        "Chunk", back_populates="file", cascade="all, delete-orphan"
    )
    processing_jobs: Mapped[list[ProcessingJob]] = relationship(
        "ProcessingJob", back_populates="file", cascade="all, delete-orphan"
    )
    tag_links: Mapped[list["FileTagLink"]] = relationship(
        "FileTagLink", back_populates="file", cascade="all, delete-orphan"
    )

    @property
    def tags(self) -> list[str]:
        """Sortierte Liste der Tag-Namen dieser Datei (ueber file_tags-Verknuepfungstabelle)."""
        return sorted(link.tag.name for link in self.tag_links)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("files.id"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str | None] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(Text)
    chroma_collection: Mapped[str | None] = mapped_column(String(64))
    chroma_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(32), nullable=False, default=_now_iso)

    file: Mapped[File] = relationship("File", back_populates="chunks")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    file_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("files.id"), index=True)
    job_type: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    started_at: Mapped[str | None] = mapped_column(String(32))
    finished_at: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)
    log: Mapped[str | None] = mapped_column(Text)

    file: Mapped[File | None] = relationship("File", back_populates="processing_jobs")


class Backup(Base):
    __tablename__ = "backups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    backup_path: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[str | None] = mapped_column(String(32))
    finished_at: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(32))
    files_copied: Mapped[int | None] = mapped_column(Integer)
    bytes_copied: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(String(32))


class Tag(Base):
    """Globale Liste frei vergebener Tags (z.B. Rechnung, Arzt, Homoeopathie). Erweiterbar per KI oder Nutzer."""
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(16), nullable=False, default="user")  # "user" | "ai" | "system"
    created_at: Mapped[str] = mapped_column(String(32), nullable=False, default=_now_iso)

    file_links: Mapped[list["FileTagLink"]] = relationship(
        "FileTagLink", back_populates="tag", cascade="all, delete-orphan"
    )


class FileTagLink(Base):
    """Verknuepfung zwischen einer Datei und einem Tag (many-to-many)."""
    __tablename__ = "file_tags"

    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
    added_by: Mapped[str] = mapped_column(String(16), nullable=False, default="user")  # "user" | "ai"
    created_at: Mapped[str] = mapped_column(String(32), nullable=False, default=_now_iso)

    file: Mapped[File] = relationship("File", back_populates="tag_links")
    tag: Mapped[Tag] = relationship("Tag", back_populates="file_links")


# ---------------------------------------------------------------------------
# Phase B: Face detection & location clustering
# ---------------------------------------------------------------------------

class PersonCluster(Base):
    """Gruppe von Gesichtern, die zur selben Person gehören."""
    __tablename__ = "person_clusters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    label: Mapped[str | None] = mapped_column(String(256))   # Optionaler Personenname
    created_at: Mapped[str] = mapped_column(String(32), nullable=False, default=_now_iso)
    updated_at: Mapped[str | None] = mapped_column(String(32))

    faces: Mapped[list["FaceEncoding"]] = relationship(
        "FaceEncoding", back_populates="cluster", cascade="all, delete-orphan"
    )


class FaceEncoding(Base):
    """Gesichts-Encoding für ein erkanntes Gesicht in einem Bild."""
    __tablename__ = "face_encodings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cluster_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("person_clusters.id", ondelete="SET NULL"), index=True
    )
    face_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    encoding: Mapped[str] = mapped_column(Text, nullable=False)   # JSON-Array float[128]
    bbox_top: Mapped[int | None] = mapped_column(Integer)
    bbox_right: Mapped[int | None] = mapped_column(Integer)
    bbox_bottom: Mapped[int | None] = mapped_column(Integer)
    bbox_left: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False, default=_now_iso)

    cluster: Mapped[PersonCluster | None] = relationship("PersonCluster", back_populates="faces")


class LocationCluster(Base):
    """Gruppe von Dateien, die an einem ähnlichen GPS-Standort aufgenommen wurden."""
    __tablename__ = "location_clusters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    label: Mapped[str | None] = mapped_column(String(256))
    center_lat: Mapped[str | None] = mapped_column(String(32))
    center_lon: Mapped[str | None] = mapped_column(String(32))
    radius_m: Mapped[int | None] = mapped_column(Integer)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False, default=_now_iso)
    updated_at: Mapped[str | None] = mapped_column(String(32))

    entries: Mapped[list["LocationEntry"]] = relationship(
        "LocationEntry", back_populates="cluster", cascade="all, delete-orphan"
    )


class LocationEntry(Base):
    """Verbindung zwischen Datei und Standort-Cluster."""
    __tablename__ = "location_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cluster_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("location_clusters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    latitude: Mapped[str | None] = mapped_column(String(32))
    longitude: Mapped[str | None] = mapped_column(String(32))

    cluster: Mapped[LocationCluster] = relationship("LocationCluster", back_populates="entries")

