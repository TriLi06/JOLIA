"""
Phase B: GPS-Standort-Clustering für Fotos mit EXIF-GPS-Daten.

Gruppiert Bilder mit ähnlichen GPS-Koordinaten zu Standort-Clustern.
Benötigt: pip install scikit-learn
"""
from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def extract_gps_from_sidecar(archive_path: Path) -> tuple[float, float] | None:
    """Liest GPS-Koordinaten aus dem JSON-Sidecar einer Bilddatei."""
    try:
        from app.services.sidecar_service import read_json_sidecar
        sj = read_json_sidecar(archive_path)
        if not sj:
            return None
        exif = sj.get("exif", {})
        gps_str = exif.get("GPS", "")
        if gps_str:
            parts = [p.strip() for p in gps_str.split(",")]
            if len(parts) == 2:
                return float(parts[0]), float(parts[1])
    except Exception:
        pass
    return None


def rebuild_location_clusters(db: Session, eps_km: float = 0.5) -> dict:
    """
    Führt DBSCAN-Clustering über alle Dateien mit GPS-Koordinaten durch.

    eps_km: Radius in Kilometern, innerhalb dem Punkte als gleicher Standort gelten.
    Gibt Summary-Dict zurück: {"clusters": N, "files_with_gps": M}
    """
    try:
        import numpy as np
        from sklearn.cluster import DBSCAN
    except ImportError:
        return {"error": "scikit-learn nicht installiert. Bitte 'pip install scikit-learn' ausführen."}

    from app.db.models import File, LocationCluster, LocationEntry

    # Alle Bilddateien mit GPS-Koordinaten laden
    image_files = db.query(File).filter(File.content_type == "images").all()
    coords: list[tuple[float, float]] = []
    file_ids: list[str] = []

    for f in image_files:
        gps = extract_gps_from_sidecar(Path(f.archive_path))
        if gps:
            coords.append(gps)
            file_ids.append(f.id)

    if not coords:
        return {"clusters": 0, "files_with_gps": 0}

    coords_array = np.array(coords)

    # Haversine-ähnliche Näherung: 1 Grad ≈ 111 km
    eps_deg = eps_km / 111.0
    clustering = DBSCAN(eps=eps_deg, min_samples=2, metric="euclidean", n_jobs=-1)
    labels = clustering.fit_predict(coords_array)

    # Bestehende Cluster löschen
    db.query(LocationEntry).delete()
    db.query(LocationCluster).delete()
    db.commit()

    now = datetime.now(timezone.utc).isoformat()
    cluster_map: dict[int, str] = {}

    # Cluster-Zentren berechnen und erstellen
    for label in set(labels):
        if label == -1:
            continue  # Noise: zu weit entfernt für einen Cluster
        mask = labels == label
        cluster_coords = coords_array[mask]
        center_lat = float(cluster_coords[:, 0].mean())
        center_lon = float(cluster_coords[:, 1].mean())
        # Radius schätzen (max. Abstand vom Zentrum)
        distances = [
            _haversine_m(center_lat, center_lon, float(c[0]), float(c[1]))
            for c in cluster_coords
        ]
        radius_m = int(max(distances)) if distances else 0

        cluster = LocationCluster(
            id=str(uuid.uuid4()),
            label=f"Standort {label + 1}",
            center_lat=f"{center_lat:.6f}",
            center_lon=f"{center_lon:.6f}",
            radius_m=radius_m,
            file_count=int(mask.sum()),
            created_at=now,
        )
        db.add(cluster)
        db.flush()
        cluster_map[label] = cluster.id

    # Dateien zu Clustern zuordnen
    for file_id, (lat, lon), label in zip(file_ids, coords, labels):
        if label == -1:
            continue
        entry = LocationEntry(
            id=str(uuid.uuid4()),
            file_id=file_id,
            cluster_id=cluster_map[label],
            latitude=f"{lat:.6f}",
            longitude=f"{lon:.6f}",
        )
        db.add(entry)

    db.commit()
    cluster_count = len(cluster_map)
    logger.info(
        "Standort-Clustering: %d Cluster aus %d GPS-Bildern erstellt.",
        cluster_count, len(coords)
    )
    return {"clusters": cluster_count, "files_with_gps": len(coords)}


def get_all_clusters(db: Session) -> list[dict]:
    """Gibt alle Standort-Cluster zurück."""
    from app.db.models import LocationCluster
    rows = db.query(LocationCluster).order_by(LocationCluster.file_count.desc()).all()
    return [
        {
            "id": r.id,
            "label": r.label,
            "center_lat": r.center_lat,
            "center_lon": r.center_lon,
            "radius_m": r.radius_m,
            "file_count": r.file_count,
        }
        for r in rows
    ]


def get_files_for_cluster(db: Session, cluster_id: str) -> list[str]:
    """Gibt alle file_ids eines Standort-Clusters zurück."""
    from app.db.models import LocationEntry
    rows = (
        db.query(LocationEntry.file_id)
        .filter(LocationEntry.cluster_id == cluster_id)
        .all()
    )
    return [r.file_id for r in rows]


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Berechnet Entfernung in Metern zwischen zwei GPS-Koordinaten."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
