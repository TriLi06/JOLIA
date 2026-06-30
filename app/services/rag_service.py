from __future__ import annotations

import logging

from app.services import chroma_service, embedding_service
from app.services.ollama_service import get_ollama_service

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Du bist ein lokaler Archiv-Assistent namens DocStoreAI.
Beantworte die Frage des Benutzers ausschließlich anhand der bereitgestellten Archiv-Kontexte.
Falls die Antwort nicht im Kontext enthalten ist, teile mit, dass das Archiv keine ausreichenden
Informationen enthält. Nenne immer die Quelldateien, auf denen deine Antwort basiert.
Antworte in derselben Sprache wie der Benutzer."""

_COLLECTIONS_TO_SEARCH = [
    "text_chunks",
    "image_descriptions",
    "audio_transcripts",
]


def search(query: str, n_results: int = 10, content_type: str | None = None) -> list[dict]:
    query_vec = embedding_service.embed_text(query)
    where = {"content_type": content_type} if content_type else None

    all_results: list[dict] = []
    for col in _COLLECTIONS_TO_SEARCH:
        try:
            results = chroma_service.query_collection(
                col, query_vec, n_results=n_results, where=where
            )
            for r in results:
                r["collection"] = col
            all_results.extend(results)
        except Exception as exc:
            logger.warning("Fehler bei Suche in Collection %s: %s", col, exc)

    # CLIP cross-modal Suche (Text → Bild) wenn verfügbar
    try:
        from app.services.clip_service import embed_text_clip, is_available as clip_available
        if clip_available():
            clip_vec = embed_text_clip(query)
            clip_results = chroma_service.query_collection(
                "image_embeddings", clip_vec, n_results=n_results
            )
            for r in clip_results:
                r["collection"] = "image_embeddings"
                r["search_type"] = "clip_similarity"
            all_results.extend(clip_results)
    except Exception as exc:
        logger.debug("CLIP cross-modal Suche nicht verfügbar: %s", exc)

    # Nach Score sortieren, Duplikate (gleiche file_id) zusammenführen
    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results[:n_results]


def search_similar_images(file_id: str, n_results: int = 10) -> list[dict]:
    """Sucht Bilder ähnlich zu einem gegebenen Bild über CLIP-Vektoren."""
    try:
        from app.services.clip_service import is_available as clip_available
        if not clip_available():
            return []
        # CLIP-Vektor des Referenzbildes aus ChromaDB laden
        existing = chroma_service.get_by_ids("image_embeddings", [f"clip_{file_id}"])
        if not existing or not existing.get("embeddings"):
            return []
        ref_vec = existing["embeddings"][0]
        results = chroma_service.query_collection(
            "image_embeddings", ref_vec, n_results=n_results + 1
        )
        # Referenzbild selbst aus Ergebnissen filtern
        return [r for r in results if r.get("metadata", {}).get("file_id") != file_id][:n_results]
    except Exception as exc:
        logger.warning("Ähnlichkeitssuche fehlgeschlagen für %s: %s", file_id, exc)
        return []


def search_similar_by_file(file_id: str, n_results: int = 10) -> list[dict]:
    """Findet semantisch ähnliche Dateien anhand der Embeddings des ersten Chunks."""
    try:
        from app.db.database import _SessionLocal
        from app.db.models import Chunk
        if _SessionLocal is None:
            return []
        db = _SessionLocal()
        try:
            first_chunk = (
                db.query(Chunk)
                .filter(Chunk.file_id == file_id)
                .order_by(Chunk.chunk_index)
                .first()
            )
            if not first_chunk:
                return []
            query_text = first_chunk.text
        finally:
            db.close()

        query_vec = embedding_service.embed_text(query_text)
        all_results: list[dict] = []
        for col in _COLLECTIONS_TO_SEARCH:
            try:
                results = chroma_service.query_collection(col, query_vec, n_results=n_results * 2)
                for r in results:
                    r["collection"] = col
                all_results.extend(results)
            except Exception as exc:
                logger.warning("Fehler bei Ähnlichkeitssuche in Collection %s: %s", col, exc)

        # Eigene Datei herausfiltern, nach file_id deduplizieren, nach Score sortieren
        seen_file_ids: set[str] = {file_id}
        deduped: list[dict] = []
        all_results.sort(key=lambda x: x["score"], reverse=True)
        for r in all_results:
            fid = r.get("metadata", {}).get("file_id", "")
            if fid and fid not in seen_file_ids:
                seen_file_ids.add(fid)
                deduped.append(r)
            if len(deduped) >= n_results:
                break
        return deduped

    except Exception as exc:
        logger.warning("search_similar_by_file fehlgeschlagen für %s: %s", file_id, exc)
        return []


def search_similar_persons(file_id: str, n_results: int = 20) -> list[dict]:
    """Findet Bilder mit gleichen Personen via FaceEncoding-Cluster."""
    try:
        from app.db.database import _SessionLocal
        from app.db.models import FaceEncoding, File
        if _SessionLocal is None:
            return []
        db = _SessionLocal()
        try:
            # Cluster-IDs der Gesichter in diesem Bild ermitteln
            face_rows = db.query(FaceEncoding).filter(FaceEncoding.file_id == file_id).all()
            cluster_ids = {fe.cluster_id for fe in face_rows if fe.cluster_id}
            if not cluster_ids:
                return []
            # Andere Bilder mit gleichen Cluster-IDs finden
            other_faces = (
                db.query(FaceEncoding)
                .filter(FaceEncoding.cluster_id.in_(cluster_ids))
                .filter(FaceEncoding.file_id != file_id)
                .all()
            )
            other_file_ids = list({fe.file_id for fe in other_faces})[:n_results]
            files = db.query(File).filter(File.id.in_(other_file_ids)).all()
        finally:
            db.close()

        return [
            {
                "id": f.id,
                "file_id": f.id,
                "text": f.ai_summary or f.original_filename,
                "score": 1.0,
                "metadata": {
                    "file_id": f.id,
                    "file_name": f.original_filename,
                    "source_path": f.archive_path,
                    "content_type": f.content_type or "images",
                },
                "collection": "face_clusters",
            }
            for f in files
        ]
    except Exception as exc:
        logger.warning("search_similar_persons fehlgeschlagen für %s: %s", file_id, exc)
        return []


def search_similar_location(file_id: str, n_results: int = 20) -> list[dict]:
    """Findet Bilder am gleichen GPS-Standort via LocationCluster."""
    try:
        from app.db.database import _SessionLocal
        from app.db.models import File, LocationEntry
        if _SessionLocal is None:
            return []
        db = _SessionLocal()
        try:
            loc = db.query(LocationEntry).filter(LocationEntry.file_id == file_id).first()
            if not loc or not loc.cluster_id:
                return []
            others = (
                db.query(LocationEntry)
                .filter(LocationEntry.cluster_id == loc.cluster_id)
                .filter(LocationEntry.file_id != file_id)
                .limit(n_results)
                .all()
            )
            other_file_ids = [e.file_id for e in others]
            files = db.query(File).filter(File.id.in_(other_file_ids)).all()
        finally:
            db.close()

        return [
            {
                "id": f.id,
                "file_id": f.id,
                "text": f.ai_summary or f.original_filename,
                "score": 1.0,
                "metadata": {
                    "file_id": f.id,
                    "file_name": f.original_filename,
                    "source_path": f.archive_path,
                    "content_type": f.content_type or "images",
                },
                "collection": "location_clusters",
            }
            for f in files
        ]
    except Exception as exc:
        logger.warning("search_similar_location fehlgeschlagen für %s: %s", file_id, exc)
        return []


def search_similar_date(file_id: str, n_results: int = 20) -> list[dict]:
    """Findet Bilder vom gleichen Aufnahmetag (aus EXIF created_at oder imported_at)."""
    try:
        from app.db.database import _SessionLocal
        from app.db.models import File
        from app.services import sidecar_service
        if _SessionLocal is None:
            return []
        db = _SessionLocal()
        try:
            ref_file = db.get(File, file_id)
            if not ref_file:
                return []

            # Datum aus Sidecar-JSON (EXIF) lesen
            date_prefix = None
            if ref_file.archive_path:
                from pathlib import Path
                sd = sidecar_service.read_json_sidecar(Path(ref_file.archive_path))
                if sd:
                    exif = sd.get("exif", {})
                    dt = (
                        exif.get("DateTimeOriginal")
                        or exif.get("DateTime")
                        or exif.get("DateTimeDigitized")
                    )
                    if dt:
                        # Format: "2024:06:15 14:30:00" → Datum-Prefix "2024:06:15"
                        date_prefix = str(dt)[:10]

            # Fallback: imported_at
            if not date_prefix and ref_file.imported_at:
                date_prefix = ref_file.imported_at[:10]

            if not date_prefix:
                return []

            # Andere Bilder mit gleichem created_at-Präfix suchen (EXIF aus imported_at)
            # Einfacher Ansatz: alle anderen Bilder laden und per Sidecar-Datum filtern
            candidates = (
                db.query(File)
                .filter(File.content_type == "images")
                .filter(File.id != file_id)
                .filter(File.status.in_(["processed", "needs_review"]))
                .limit(500)
                .all()
            )
        finally:
            db.close()

        # Datum-Filter via Sidecar
        matched = []
        from pathlib import Path
        for f in candidates:
            try:
                sd = sidecar_service.read_json_sidecar(Path(f.archive_path))
                if sd:
                    exif = sd.get("exif", {})
                    dt = (
                        exif.get("DateTimeOriginal")
                        or exif.get("DateTime")
                        or exif.get("DateTimeDigitized")
                    )
                    if dt and str(dt)[:10] == date_prefix:
                        matched.append(f)
                else:
                    # Fallback: imported_at
                    if f.imported_at and f.imported_at[:10] == date_prefix:
                        matched.append(f)
            except Exception:
                pass
            if len(matched) >= n_results:
                break

        return [
            {
                "id": f.id,
                "file_id": f.id,
                "text": f.ai_summary or f.original_filename,
                "score": 1.0,
                "metadata": {
                    "file_id": f.id,
                    "file_name": f.original_filename,
                    "source_path": f.archive_path,
                    "content_type": f.content_type or "images",
                },
                "collection": "date_filter",
            }
            for f in matched
        ]
    except Exception as exc:
        logger.warning("search_similar_date fehlgeschlagen für %s: %s", file_id, exc)
        return []


def chat(question: str, n_context: int = 6) -> dict:
    retrieval_results = search(question, n_results=n_context)

    if not retrieval_results:
        return {
            "answer": "Das Archiv enthält keine Informationen zu dieser Frage.",
            "sources": [],
        }

    # Kontext aufbauen
    context_parts = []
    sources = []
    seen_files: set[str] = set()

    for r in retrieval_results:
        meta = r.get("metadata", {})
        file_name = meta.get("file_name", "Unbekannte Datei")
        source_path = meta.get("source_path", "")
        snippet = r["text"][:500]
        context_parts.append(f"[Quelle: {file_name}]\n{snippet}")
        if source_path not in seen_files:
            seen_files.add(source_path)
            sources.append(
                {
                    "file_id": meta.get("file_id", ""),
                    "file_name": file_name,
                    "source_path": source_path,
                    "content_type": meta.get("content_type", ""),
                    "score": round(r["score"], 3),
                }
            )

    context_text = "\n\n---\n\n".join(context_parts)
    prompt = (
        f"Benutzerfrage:\n{question}\n\n"
        f"Archiv-Kontext:\n{context_text}\n\n"
        f"Quellen: {', '.join(s['file_name'] for s in sources)}\n\nAntwort:"
    )

    ollama = get_ollama_service()
    if not ollama.is_available():
        return {
            "answer": "Fehler: Ollama-Dienst ist nicht erreichbar. Bitte Ollama starten.",
            "sources": sources,
        }

    try:
        answer = ollama.generate(prompt, system=SYSTEM_PROMPT)
    except Exception as exc:
        logger.error("LLM-Fehler: %s", exc)
        answer = f"Fehler bei der Antwortgenerierung: {exc}"

    return {"answer": answer, "sources": sources}
