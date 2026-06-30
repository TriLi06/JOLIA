from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.db import repositories as repo
from app.services import rag_service

router = APIRouter()


class SearchResult(BaseModel):
    id: str
    file_id: str
    text: str
    score: float
    file_name: str
    source_path: str
    content_type: str
    collection: str
    page: int | None = None
    summary: str | None = None
    thumbnail_url: str | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    total: int


@router.get("", response_model=SearchResponse)
def search(
    q: str,
    n: int = 10,
    content_type: str | None = None,
    db: Session = Depends(get_session),
):
    if not q.strip():
        return SearchResponse(query=q, results=[], total=0)

    raw_results = rag_service.search(q, n_results=n, content_type=content_type)

    # Datei-Metadaten (summary, thumbnail) aus DB nachladen
    file_ids = list({r.get("metadata", {}).get("file_id", "") for r in raw_results if r.get("metadata", {}).get("file_id")})
    file_map = {}
    if file_ids:
        for fid in file_ids:
            f = repo.get_file_by_id(db, fid)
            if f:
                file_map[fid] = f

    results = []
    for r in raw_results:
        fid = r.get("metadata", {}).get("file_id", "")
        f = file_map.get(fid)
        ct = r.get("metadata", {}).get("content_type", "")
        results.append(SearchResult(
            id=r["id"],
            file_id=fid,
            text=r["text"][:300],
            score=round(r["score"], 3),
            file_name=r.get("metadata", {}).get("file_name", ""),
            source_path=r.get("metadata", {}).get("source_path", ""),
            content_type=ct,
            collection=r.get("collection", ""),
            page=r.get("metadata", {}).get("page") or None,
            summary=f.ai_summary if f else None,
            thumbnail_url=f"/api/files/{fid}/thumbnail" if (f and f.content_type == "images") else None,
        ))
    return SearchResponse(query=q, results=results, total=len(results))


# ---------------------------------------------------------------------------
# Phase C: Bild-Ähnlichkeitssuche (CLIP)
# ---------------------------------------------------------------------------

class ImageSimilarityResult(BaseModel):
    file_id: str
    file_name: str
    source_path: str
    score: float


class ImageSimilarityResponse(BaseModel):
    results: list[ImageSimilarityResult]
    total: int


@router.post("/image-similarity", response_model=ImageSimilarityResponse)
async def image_similarity_search(
    file: UploadFile = File(...),
    n: int = 10,
):
    """
    Lädt ein Bild hoch und sucht ähnliche Bilder via CLIP-Embedding.
    Setzt voraus, dass enable_clip_embeddings=true und Bilder bereits indexiert sind.
    """
    from app.services.clip_service import embed_image, is_available
    from app.services import chroma_service
    from app.config import get_config
    import tempfile
    from pathlib import Path

    if not is_available():
        raise HTTPException(
            status_code=501,
            detail="CLIP nicht verfügbar. Bitte 'pip install open-clip-torch' installieren.",
        )

    cfg = get_config()
    # Bild temporär speichern
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=Path(file.filename or "q.jpg").suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        clip_vec = embed_image(
            tmp_path,
            model_name=cfg.models.clip_model,
            pretrained=cfg.models.clip_pretrained,
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    raw = chroma_service.query_collection(
        collection_name="image_embeddings",
        query_embedding=clip_vec,
        n_results=n,
    )

    results = [
        ImageSimilarityResult(
            file_id=r.get("metadata", {}).get("file_id", ""),
            file_name=r.get("metadata", {}).get("file_name", ""),
            source_path=r.get("metadata", {}).get("source_path", ""),
            score=round(r["score"], 3),
        )
        for r in raw
    ]
    return ImageSimilarityResponse(results=results, total=len(results))


# ---------------------------------------------------------------------------
# Phase C: Gesichts-Cluster-Suche
# ---------------------------------------------------------------------------

class PersonClusterInfo(BaseModel):
    id: str
    label: str | None
    face_count: int
    created_at: str


@router.get("/faces", response_model=list[PersonClusterInfo])
def list_face_clusters(db: Session = Depends(get_session)):
    """Listet alle Personen-Cluster (erkannte Gesichtsgruppen)."""
    from app.services.face_service import get_all_clusters
    return [PersonClusterInfo(**c) for c in get_all_clusters(db)]


@router.get("/faces/{cluster_id}/files")
def files_for_face_cluster(cluster_id: str, db: Session = Depends(get_session)):
    """Gibt alle Dateien zurück, die Gesichter eines bestimmten Clusters enthalten."""
    from app.services.face_service import get_files_for_cluster
    from app.db import repositories as repo
    file_ids = get_files_for_cluster(db, cluster_id)
    files = [repo.get_file_by_id(db, fid) for fid in file_ids]
    return [
        {"id": f.id, "original_filename": f.original_filename, "archive_path": f.archive_path}
        for f in files if f
    ]


@router.post("/faces/rebuild-clusters")
def rebuild_face_clusters(db: Session = Depends(get_session)):
    """Führt DBSCAN-Clustering über alle Gesichts-Encodings neu durch."""
    from app.services.face_service import rebuild_person_clusters
    result = rebuild_person_clusters(db)
    if "error" in result:
        raise HTTPException(status_code=501, detail=result["error"])
    return result


class RenameFaceClusterRequest(BaseModel):
    label: str


@router.patch("/faces/{cluster_id}/label")
def rename_face_cluster(cluster_id: str, body: RenameFaceClusterRequest, db: Session = Depends(get_session)):
    """Weist einem Personen-Cluster einen Namen zu (z.B. 'Max Mustermann')."""
    from app.db.models import PersonCluster
    from datetime import datetime, timezone
    cluster = db.get(PersonCluster, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster nicht gefunden")
    cluster.label = body.label.strip()
    cluster.updated_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    return {"id": cluster_id, "label": cluster.label}


@router.get("/faces/{cluster_id}/thumbnail")
def face_cluster_thumbnail(cluster_id: str, size: int = 96, db: Session = Depends(get_session)):
    """Liefert ein quadratisches Ausschnitts-Bild des repräsentativsten Gesichts im Cluster."""
    from app.db.models import FaceEncoding
    from app.config import get_config
    from pathlib import Path

    face = (
        db.query(FaceEncoding)
        .filter(FaceEncoding.cluster_id == cluster_id)
        .first()
    )
    if not face:
        raise HTTPException(status_code=404, detail="Kein Gesicht für diesen Cluster gefunden")

    file_record = repo.get_file_by_id(db, face.file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="Quelldatei nicht gefunden")

    cfg = get_config()
    archive_path = Path(file_record.archive_path)
    if not archive_path.is_absolute():
        archive_path = cfg.paths.archive_root / archive_path
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail="Bilddatei nicht gefunden")

    try:
        from PIL import Image
        img = Image.open(str(archive_path)).convert("RGB")
        top, right, bottom, left = face.bbox_top or 0, face.bbox_right or img.width, face.bbox_bottom or img.height, face.bbox_left or 0

        # Polsterung hinzufügen (25 % der Gesichtsgröße)
        face_h = bottom - top
        face_w = right - left
        pad_y = int(face_h * 0.35)
        pad_x = int(face_w * 0.35)
        top = max(0, top - pad_y)
        left = max(0, left - pad_x)
        bottom = min(img.height, bottom + pad_y)
        right = min(img.width, right + pad_x)

        cropped = img.crop((left, top, right, bottom))
        cropped = cropped.resize((size, size), Image.LANCZOS)

        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        return Response(content=buf.read(), media_type="image/jpeg")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Thumbnail-Fehler: {exc}")


@router.get("/similar-images/{file_id}", response_model=ImageSimilarityResponse)
def similar_images_by_id(file_id: str, n: int = 10):
    """Findet Bilder ähnlich zu einem bereits indexierten Bild (via CLIP, nach file_id)."""
    results_raw = rag_service.search_similar_images(file_id, n_results=n)
    results = [
        ImageSimilarityResult(
            file_id=r.get("metadata", {}).get("file_id", ""),
            file_name=r.get("metadata", {}).get("file_name", ""),
            source_path=r.get("metadata", {}).get("source_path", ""),
            score=round(r["score"], 3),
        )
        for r in results_raw
    ]
    return ImageSimilarityResponse(results=results, total=len(results))


# ---------------------------------------------------------------------------
# Phase C: Standort-Cluster-Suche
# ---------------------------------------------------------------------------

class LocationClusterInfo(BaseModel):
    id: str
    label: str | None
    center_lat: str | None
    center_lon: str | None
    radius_m: int | None
    file_count: int


@router.get("/locations", response_model=list[LocationClusterInfo])
def list_location_clusters(db: Session = Depends(get_session)):
    """Listet alle GPS-Standort-Cluster."""
    from app.services.location_service import get_all_clusters
    return [LocationClusterInfo(**c) for c in get_all_clusters(db)]


@router.get("/locations/{cluster_id}/files")
def files_for_location_cluster(cluster_id: str, db: Session = Depends(get_session)):
    """Gibt alle Dateien eines Standort-Clusters zurück."""
    from app.services.location_service import get_files_for_cluster
    from app.db import repositories as repo
    file_ids = get_files_for_cluster(db, cluster_id)
    files = [repo.get_file_by_id(db, fid) for fid in file_ids]
    return [
        {
            "id": f.id,
            "original_filename": f.original_filename,
            "archive_path": f.archive_path,
        }
        for f in files if f
    ]


@router.post("/locations/rebuild-clusters")
def rebuild_location_clusters(
    eps_km: float = 0.5,
    db: Session = Depends(get_session),
):
    """Führt GPS-DBSCAN-Clustering neu durch."""
    from app.services.location_service import rebuild_location_clusters as _rebuild
    result = _rebuild(db, eps_km=eps_km)
    if "error" in result:
        raise HTTPException(status_code=501, detail=result["error"])
    return result

