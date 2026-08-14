"""
Phase B: Gesichtserkennung und Cluster-Verwaltung.

Benötigt: pip install face-recognition  (beinhaltet dlib, CPU-kompatibel)
Aktivierung in config.yaml:
    processing:
      enable_face_detection: true
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def is_available() -> bool:
    try:
        import face_recognition  # noqa: F401
        return True
    except (ImportError, SystemExit) as exc:
        # face_recognition/api.py calls quit() (-> SystemExit) if its model
        # package fails to import, so we must catch that too, not just ImportError.
        logger.warning("face_recognition nicht verfügbar: %s", exc)
        return False


def detect_and_store_faces(file_path: Path, file_id: str, db: Session) -> int:
    """
    Erkennt Gesichter in einem Bild, speichert Encodings in der DB
    und gibt die Anzahl erkannter Gesichter zurück.
    """
    if not is_available():
        logger.warning("face_recognition nicht installiert – Gesichtserkennung übersprungen.")
        return 0
    try:
        import face_recognition as fr
        import numpy as np
        from PIL import Image

        img_pil = Image.open(str(file_path)).convert("RGB")
        # Größe begrenzen für Performance
        max_dim = 1024
        if max(img_pil.size) > max_dim:
            ratio = max_dim / max(img_pil.size)
            img_pil = img_pil.resize(
                (int(img_pil.width * ratio), int(img_pil.height * ratio))
            )
        img_array = np.array(img_pil)

        locations = fr.face_locations(img_array, model="hog")  # hog = CPU-freundlich
        encodings = fr.face_encodings(img_array, locations)
    except Exception as exc:
        logger.warning("Gesichtserkennung fehlgeschlagen für %s: %s", file_path.name, exc)
        return 0

    if not encodings:
        return 0

    from app.db.models import FaceEncoding
    now = datetime.now().isoformat()

    for i, (encoding, location) in enumerate(zip(encodings, locations)):
        top, right, bottom, left = location
        fe = FaceEncoding(
            id=str(uuid.uuid4()),
            file_id=file_id,
            face_index=i,
            encoding=json.dumps(encoding.tolist()),
            bbox_top=top,
            bbox_right=right,
            bbox_bottom=bottom,
            bbox_left=left,
        )
        db.add(fe)
    db.commit()
    logger.info("Gesichtserkennung: %d Gesicht(er) in %s gespeichert.", len(encodings), file_path.name)
    return len(encodings)


def rebuild_person_clusters(db: Session) -> dict:
    """
    Führt DBSCAN-Clustering über alle gespeicherten Gesichts-Encodings durch
    und aktualisiert die PersonCluster-Tabelle.
    """
    try:
        import numpy as np
        from sklearn.cluster import DBSCAN
    except ImportError:
        return {"error": "scikit-learn nicht installiert. Bitte 'pip install scikit-learn' ausführen."}

    from app.db.models import FaceEncoding, PersonCluster

    # Alle Encodings laden
    all_encodings = db.query(FaceEncoding).all()
    if not all_encodings:
        return {"clusters": 0, "faces": 0}

    encodings_array = np.array([json.loads(fe.encoding) for fe in all_encodings])

    # DBSCAN: eps=0.6 ist typisch für face_recognition (L2-Distanz)
    clustering = DBSCAN(eps=0.6, min_samples=1, metric="euclidean", n_jobs=-1)
    labels = clustering.fit_predict(encodings_array)

    # Bestehende manuell vergebene Labels sichern (face_id → label)
    # Wir merken uns, welche Encodings in welchem Cluster mit welchem Label waren.
    # Strategie: Wenn die Mehrheit der Encodings eines neuen Clusters vorher dasselbe
    # benannte Cluster hatte, wird das Label übernommen.
    old_cluster_labels: dict[str, str] = {}
    existing_clusters = db.query(PersonCluster).all()
    for c in existing_clusters:
        if c.label and not c.label.startswith("Person "):
            old_cluster_labels[c.id] = c.label

    # Alte Cluster-Zuordnung je Gesicht sichern, BEVOR die Cluster gelöscht werden.
    # Nach dem DELETE + commit wird fe.cluster_id (ON DELETE SET NULL bzw. Session-Expiry)
    # auf NULL zurückgesetzt - würden wir es erst in der Abstimmungsschleife lesen, gingen
    # alle manuell vergebenen Personennamen bei jedem Re-Clustering verloren.
    old_face_cluster: dict[str, str] = {
        fe.id: fe.cluster_id for fe in all_encodings if fe.cluster_id
    }

    # Bestehende Cluster löschen
    db.query(PersonCluster).delete()
    db.commit()

    # Cluster-Mapping: dbscan_label → PersonCluster
    cluster_map: dict[int, str] = {}
    now = datetime.now().isoformat()

    # Für jedes neue DBSCAN-Cluster prüfen ob ein manueller Name übernommen werden kann
    dbscan_label_to_faces: dict[int, list] = {}
    for fe, lbl in zip(all_encodings, labels):
        if lbl != -1:
            dbscan_label_to_faces.setdefault(lbl, []).append(fe)

    for dbscan_lbl, faces_in_cluster in dbscan_label_to_faces.items():
        # Versuche dominantes altes Label zu finden
        old_label_votes: dict[str, int] = {}
        for fe in faces_in_cluster:
            old_cid = old_face_cluster.get(fe.id)
            if old_cid and old_cid in old_cluster_labels:
                name = old_cluster_labels[old_cid]
                old_label_votes[name] = old_label_votes.get(name, 0) + 1
        if old_label_votes:
            inherited_label = max(old_label_votes, key=old_label_votes.__getitem__)
        else:
            inherited_label = f"Person {dbscan_lbl + 1}"
        cluster = PersonCluster(
            id=str(uuid.uuid4()),
            label=inherited_label,
            created_at=now,
        )
        db.add(cluster)
        db.flush()
        cluster_map[dbscan_lbl] = cluster.id

    # Encodings zu Clustern zuordnen
    for fe, label in zip(all_encodings, labels):
        fe.cluster_id = cluster_map.get(label)

    db.commit()

    cluster_count = len(cluster_map)
    logger.info("Gesichts-Clustering: %d Cluster aus %d Gesichtern erstellt.", cluster_count, len(all_encodings))
    return {"clusters": cluster_count, "faces": len(all_encodings)}


def get_all_clusters(db: Session) -> list[dict]:
    """Gibt alle Personen-Cluster mit Gesichtsanzahl zurück."""
    from app.db.models import FaceEncoding, PersonCluster
    from sqlalchemy import func

    rows = (
        db.query(
            PersonCluster.id,
            PersonCluster.label,
            PersonCluster.created_at,
            func.count(FaceEncoding.id).label("face_count"),
        )
        .outerjoin(FaceEncoding, FaceEncoding.cluster_id == PersonCluster.id)
        .group_by(PersonCluster.id)
        .all()
    )
    return [
        {"id": r.id, "label": r.label, "face_count": r.face_count, "created_at": r.created_at}
        for r in rows
    ]


def _is_auto_label(label: str | None) -> bool:
    """True für leere oder automatisch generierte Labels ('Person N')."""
    if not label or not label.strip():
        return True
    return label.strip().startswith("Person ")


def get_person_groups(db: Session) -> list[dict]:
    """Fasst Cluster mit identischem (manuell vergebenem) Namen zu einer Person zusammen.

    Mehrere DBSCAN-Cluster können dieselbe Person unter unterschiedlichen
    Bedingungen (z.B. Beleuchtung) zeigen. Wurde ihnen derselbe Name gegeben
    (bzw. wurden sie zusammengeführt), erscheinen sie hier als EINE Person.
    Unbenannte Cluster bleiben jeweils eigenständig.
    """
    clusters = get_all_clusters(db)

    named: dict[str, dict] = {}
    groups: list[dict] = []

    for c in clusters:
        label = (c["label"] or "").strip()
        if _is_auto_label(label):
            groups.append(
                {
                    "key": c["id"],
                    "label": label,  # ggf. "Person N" oder leer
                    "named": False,
                    "cluster_ids": [c["id"]],
                    "face_count": c["face_count"],
                    "thumb_cluster_id": c["id"],
                    "thumb_face_count": c["face_count"],
                }
            )
            continue

        g = named.get(label)
        if g is None:
            g = {
                "key": "name:" + label,
                "label": label,
                "named": True,
                "cluster_ids": [c["id"]],
                "face_count": c["face_count"],
                "thumb_cluster_id": c["id"],
                "thumb_face_count": c["face_count"],
            }
            named[label] = g
            groups.append(g)
        else:
            g["cluster_ids"].append(c["id"])
            g["face_count"] += c["face_count"]
            # Thumbnail vom Cluster mit den meisten Gesichtern nehmen
            if c["face_count"] > g["thumb_face_count"]:
                g["thumb_cluster_id"] = c["id"]
                g["thumb_face_count"] = c["face_count"]

    # Benannte Personen alphabetisch zuerst, dann unbenannte nach Fotoanzahl
    groups.sort(
        key=lambda g: (
            0 if g["named"] else 1,
            g["label"].lower() if g["named"] else "",
            -g["face_count"],
        )
    )
    return groups


def set_label_for_clusters(db: Session, cluster_ids: list[str], label: str) -> int:
    """Setzt bei mehreren Clustern denselben Namen (= Zusammenführen zu einer Person)."""
    from app.db.models import PersonCluster

    label = (label or "").strip()
    if not label or not cluster_ids:
        return 0
    now = datetime.now().isoformat()
    updated = 0
    for cid in cluster_ids:
        cluster = db.get(PersonCluster, cid)
        if cluster:
            cluster.label = label
            cluster.updated_at = now
            updated += 1
    db.commit()
    return updated


def get_files_for_cluster(db: Session, cluster_id: str) -> list[str]:
    """Gibt alle file_ids zurück, die Gesichter aus diesem Cluster enthalten."""
    from app.db.models import FaceEncoding

    rows = (
        db.query(FaceEncoding.file_id)
        .filter(FaceEncoding.cluster_id == cluster_id)
        .distinct()
        .all()
    )
    return [r.file_id for r in rows]


def get_person_names_for_file(db: Session, file_id: str) -> list[str]:
    """Gibt die benannten Personen zurück, deren Gesichter in einer Datei erkannt wurden.

    Automatisch generierte Cluster-Labels ("Person N") werden ausgeblendet -
    nur manuell vergebene Namen gelten als "Personen-Tags".
    """
    from app.db.models import FaceEncoding, PersonCluster

    rows = (
        db.query(PersonCluster.label)
        .join(FaceEncoding, FaceEncoding.cluster_id == PersonCluster.id)
        .filter(FaceEncoding.file_id == file_id)
        .filter(PersonCluster.label.isnot(None))
        .distinct()
        .all()
    )
    names = [
        r.label.strip()
        for r in rows
        if r.label and r.label.strip() and not r.label.strip().startswith("Person ")
    ]
    # Deduplizieren unter Beibehaltung der Reihenfolge, alphabetisch sortiert
    return sorted(dict.fromkeys(names))


def get_person_names_for_files(db: Session, file_ids: list[str]) -> dict[str, list[str]]:
    """Wie get_person_names_for_file, aber gebündelt für mehrere Dateien (eine Query)."""
    from app.db.models import FaceEncoding, PersonCluster

    if not file_ids:
        return {}
    rows = (
        db.query(FaceEncoding.file_id, PersonCluster.label)
        .join(PersonCluster, FaceEncoding.cluster_id == PersonCluster.id)
        .filter(FaceEncoding.file_id.in_(file_ids))
        .filter(PersonCluster.label.isnot(None))
        .distinct()
        .all()
    )
    result: dict[str, set[str]] = {}
    for file_id, label in rows:
        if label and label.strip() and not label.strip().startswith("Person "):
            result.setdefault(file_id, set()).add(label.strip())
    return {fid: sorted(names) for fid, names in result.items()}
