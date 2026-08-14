from __future__ import annotations

import logging

from app.services import chroma_service, embedding_service
from app.services.ollama_service import get_ollama_service

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Du bist ein lokaler Archiv-Assistent namens JOLIA Docs.
Beantworte die Frage des Benutzers ausschließlich anhand der bereitgestellten Archiv-Kontexte.
Falls die Antwort nicht im Kontext enthalten ist, teile mit, dass das Archiv keine ausreichenden
Informationen enthält. Nenne immer die Quelldateien, auf denen deine Antwort basiert.
Wenn bei einer Quelle eine Zeile "Auf diesem Bild sind folgende Personen zu sehen: …" steht,
ist das eine verlässliche Angabe der Gesichtserkennung: die genannten Personen sind auf diesem
Bild tatsächlich abgebildet. Bei Fragen nach Bildern einer bestimmten Person liste genau die
Quelldateien auf, deren Personen-Zeile diese Person enthält.
Antworte in derselben Sprache wie der Benutzer."""

_COLLECTIONS_TO_SEARCH = [
    "text_chunks",
    "image_descriptions",
    "audio_transcripts",
]


_RRF_K = 60  # üblicher Dämpfungsfaktor für Reciprocal Rank Fusion


def search(
    query: str,
    n_results: int = 10,
    content_type: str | None = None,
    tags: list[str] | None = None,
) -> list[dict]:
    query_vec = embedding_service.embed_text(query)
    where = {"content_type": content_type} if content_type else None

    result_batches: list[list[dict]] = []
    for col in _COLLECTIONS_TO_SEARCH:
        try:
            results = chroma_service.query_collection(
                col, query_vec, n_results=n_results, where=where
            )
            for r in results:
                r["collection"] = col
            result_batches.append(results)
        except Exception as exc:
            logger.warning("Fehler bei Suche in Collection %s: %s", col, exc)

    # CLIP cross-modal Suche (Text → Bild) wenn verfügbar und aktiviert
    try:
        from app.config import get_config
        if getattr(get_config().processing, "enable_clip_embeddings", False):
            from app.services.clip_service import embed_text_clip, is_available as clip_available
            if clip_available():
                clip_vec = embed_text_clip(query)
                clip_results = chroma_service.query_collection(
                    "image_embeddings", clip_vec, n_results=n_results
                )
                for r in clip_results:
                    r["collection"] = "image_embeddings"
                    r["search_type"] = "clip_similarity"
                result_batches.append(clip_results)
    except Exception as exc:
        logger.debug("CLIP cross-modal Suche nicht verfügbar: %s", exc)

    # CLAP cross-modal Suche (Text → Musik/Audio) wenn verfügbar und aktiviert
    try:
        from app.config import get_config
        if getattr(get_config().processing, "enable_clap_embeddings", False):
            from app.services.clap_service import embed_text_clap, is_available as clap_available
            if clap_available():
                clap_vec = embed_text_clap(query)
                clap_results = chroma_service.query_collection(
                    "audio_embeddings", clap_vec, n_results=n_results
                )
                for r in clap_results:
                    r["collection"] = "audio_embeddings"
                    r["search_type"] = "clap_similarity"
                result_batches.append(clap_results)
    except Exception as exc:
        logger.debug("CLAP cross-modal Suche nicht verfügbar: %s", exc)

    all_results = _fuse_results(result_batches)

    # Personen-Suche: falls die Anfrage einem Gesichts-Cluster-Label entspricht
    # (z.B. "Ulrike"), Dateien mit diesem Gesicht als Top-Treffer ergänzen.
    person_results = _search_by_person_label(query, n_results)
    if person_results:
        person_ids = {r["metadata"]["file_id"] for r in person_results}
        all_results = person_results + [
            r for r in all_results if r.get("metadata", {}).get("file_id") not in person_ids
        ]

    # Tag-Suche: falls die Anfrage (ganz oder teilweise) einem vergebenen Tag
    # entspricht (z.B. "Männer"), Dateien mit diesem Tag als Top-Treffer ergänzen -
    # Embedding-Scores allein finden nicht immer alle manuell/KI-getaggten Dateien.
    tag_name_results = _search_by_tag_name(query, n_results)
    if tag_name_results:
        tag_ids = {r["metadata"]["file_id"] for r in tag_name_results}
        all_results = tag_name_results + [
            r for r in all_results if r.get("metadata", {}).get("file_id") not in tag_ids
        ]

    all_results = _exclude_deleted(all_results)
    if tags:
        all_results = _filter_by_tags(all_results, tags)
    return all_results[:n_results]


def _fuse_results(result_batches: list[list[dict]]) -> list[dict]:
    """Führt Ergebnisse mehrerer Collections/Embedding-Räume zusammen.

    Rohe Scores (Cosinus- bzw. distanzbasiert) sind zwischen unterschiedlichen
    Embedding-Modellen (Text vs. CLIP vs. CLAP) nicht direkt vergleichbar, auch
    nicht nach Normierung auf denselben Wertebereich - die Verteilungen
    unterscheiden sich zu stark (z.B. liegen CLIP-Text-Bild-Scores systematisch
    niedriger als Text-Text-Scores). Daher wird per Reciprocal Rank Fusion (RRF)
    anhand des Rangs pro Collection kombiniert; das ist robust gegenüber
    unterschiedlichen Score-Skalen und vermeidet, dass z.B. ein PDF mit
    Rohscore 0.35 ein passenderes Bild mit Rohscore 0.37 verdrängt.
    """
    fused: dict[str, dict] = {}
    for batch in result_batches:
        for rank, r in enumerate(batch):
            file_id = r.get("metadata", {}).get("file_id") or r["id"]
            rrf = 1.0 / (_RRF_K + rank + 1)
            entry = fused.get(file_id)
            if entry is None:
                entry = dict(r)
                entry["_rrf_score"] = 0.0
                fused[file_id] = entry
            fused[file_id]["_rrf_score"] += rrf
            # Bestes Original-Ergebnis (höchster Rohscore) für Anzeige/Text behalten
            if r["score"] > entry.get("score", -1):
                entry["text"] = r["text"]
                entry["metadata"] = r["metadata"]
                entry["collection"] = r["collection"]
                entry["score"] = r["score"]
                if "search_type" in r:
                    entry["search_type"] = r["search_type"]

    merged = list(fused.values())
    merged.sort(key=lambda x: x["_rrf_score"], reverse=True)
    for r in merged:
        del r["_rrf_score"]
    return merged


def _person_names_for_results(results: list[dict]) -> dict[str, list[str]]:
    """Ordnet jeder Trefferdatei die benannten erkannten Personen zu (für Chat-Kontext)."""
    try:
        from app.db.database import _SessionLocal
        if _SessionLocal is None:
            return {}
        file_ids = [
            r.get("metadata", {}).get("file_id")
            for r in results
            if r.get("metadata", {}).get("file_id")
        ]
        if not file_ids:
            return {}
        db = _SessionLocal()
        try:
            from app.services.face_service import get_person_names_for_files
            return get_person_names_for_files(db, file_ids)
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Personen-Namen für Chat-Kontext fehlgeschlagen: %s", exc)
        return {}


def _search_by_person_label(query: str, n_results: int) -> list[dict]:
    """Findet Dateien anhand eines Personennamens (Gesichts-Cluster-Label)."""
    try:
        from app.db.database import _SessionLocal
        from app.db.models import File, PersonCluster
        if _SessionLocal is None:
            return []
        db = _SessionLocal()
        try:
            # Query ist meist ein ganzer Satz ("Alle Bilder auf denen Ulrike zu sehen ist"),
            # das Label dagegen nur der Name selbst - daher muss geprueft werden, ob das
            # Label als Teilstring IN der Query vorkommt (nicht umgekehrt).
            query_lower = query.lower()
            clusters = db.query(PersonCluster).filter(PersonCluster.label.isnot(None)).all()
            matched = [
                c for c in clusters
                if c.label and c.label.strip().lower() in query_lower
            ]
            if not matched:
                return []
            from app.services.face_service import get_files_for_cluster
            file_ids: list[str] = []
            for cluster in matched:
                file_ids.extend(get_files_for_cluster(db, cluster.id))
            file_ids = list(dict.fromkeys(file_ids))[:n_results]
            if not file_ids:
                return []
            files = db.query(File).filter(File.id.in_(file_ids), File.status != "deleted").all()
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
        logger.warning("Personen-Namenssuche fehlgeschlagen für Query '%s': %s", query, exc)
        return []


def _search_by_tag_name(query: str, n_results: int) -> list[dict]:
    """Findet Dateien, deren Tag-Name als Teilstring in der Query vorkommt (z.B. "Männer")."""
    try:
        from app.db.database import _SessionLocal
        from app.db.models import File, FileTagLink, Tag
        if _SessionLocal is None:
            return []
        db = _SessionLocal()
        try:
            query_lower = query.lower()
            tags = db.query(Tag).all()
            matched = [t for t in tags if t.name and t.name.strip().lower() in query_lower]
            if not matched:
                return []
            tag_ids = [t.id for t in matched]
            file_ids = [
                fid for (fid,) in db.query(FileTagLink.file_id)
                .filter(FileTagLink.tag_id.in_(tag_ids))
                .all()
            ]
            file_ids = list(dict.fromkeys(file_ids))[:n_results]
            if not file_ids:
                return []
            files = db.query(File).filter(File.id.in_(file_ids), File.status != "deleted").all()
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
                    "content_type": f.content_type or "documents",
                },
                "collection": "tag_match",
            }
            for f in files
        ]
    except Exception as exc:
        logger.warning("Tag-Namenssuche fehlgeschlagen für Query '%s': %s", query, exc)
        return []


def _exclude_deleted(results: list[dict]) -> list[dict]:
    """Entfernt Treffer, deren Datei als 'deleted' markiert wurde (Soft-Delete)."""
    try:
        from app.db.database import _SessionLocal
        from app.db.models import File
        if _SessionLocal is None:
            return results
        db = _SessionLocal()
        try:
            file_ids = {r.get("metadata", {}).get("file_id") for r in results if r.get("metadata", {}).get("file_id")}
            if not file_ids:
                return results
            deleted_ids = {
                f.id for f in db.query(File.id).filter(
                    File.id.in_(file_ids), File.status == "deleted"
                ).all()
            }
        finally:
            db.close()
        if not deleted_ids:
            return results
        return [r for r in results if r.get("metadata", {}).get("file_id") not in deleted_ids]
    except Exception as exc:
        logger.warning("Deleted-Filter fehlgeschlagen: %s", exc)
        return results


def _filter_by_tags(results: list[dict], tags: list[str]) -> list[dict]:
    """Behaelt nur Treffer, deren Datei mindestens einen der gewuenschten Tags besitzt (OR)."""
    try:
        from app.db.database import _SessionLocal
        from app.db.models import FileTagLink, Tag
        if _SessionLocal is None:
            return results
        db = _SessionLocal()
        try:
            file_ids = {r.get("metadata", {}).get("file_id") for r in results if r.get("metadata", {}).get("file_id")}
            if not file_ids:
                return []
            matching_ids = {
                fid for (fid,) in db.query(FileTagLink.file_id)
                .join(Tag, Tag.id == FileTagLink.tag_id)
                .filter(FileTagLink.file_id.in_(file_ids), Tag.name.in_(tags))
                .all()
            }
        finally:
            db.close()
        return [r for r in results if r.get("metadata", {}).get("file_id") in matching_ids]
    except Exception as exc:
        logger.warning("Tag-Filter fehlgeschlagen: %s", exc)
        return results


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


def search_similar_audio(file_id: str, n_results: int = 10) -> list[dict]:
    """Sucht Audio-/Musikdateien ähnlich zu einer gegebenen Datei über CLAP-Vektoren."""
    try:
        from app.services.clap_service import is_available as clap_available
        if not clap_available():
            return []
        existing = chroma_service.get_by_ids("audio_embeddings", [f"clap_{file_id}"])
        if not existing or not existing.get("embeddings"):
            return []
        ref_vec = existing["embeddings"][0]
        results = chroma_service.query_collection(
            "audio_embeddings", ref_vec, n_results=n_results + 1
        )
        return [r for r in results if r.get("metadata", {}).get("file_id") != file_id][:n_results]
    except Exception as exc:
        logger.warning("Audio-Ähnlichkeitssuche fehlgeschlagen für %s: %s", file_id, exc)
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
                from app.config import get_config
                from app.services import archive_service
                archive_path = archive_service.resolve_archive_path(ref_file.archive_path, get_config().paths.archive_root)
                sd = sidecar_service.read_json_sidecar(archive_path)
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
        from app.config import get_config
        from app.services import archive_service
        archive_root = get_config().paths.archive_root
        for f in candidates:
            try:
                archive_path = archive_service.resolve_archive_path(f.archive_path, archive_root)
                sd = sidecar_service.read_json_sidecar(archive_path)
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

    # Erkannte Personen (benannte Gesichts-Cluster) je Datei nachschlagen, damit
    # das LLM Fragen wie "Zeige mir Bilder, auf denen Thorsten zu sehen ist"
    # beantworten kann - die reinen KI-Beschreibungen enthalten die Namen nicht.
    person_names_by_file = _person_names_for_results(retrieval_results)

    for r in retrieval_results:
        meta = r.get("metadata", {})
        file_name = meta.get("file_name", "Unbekannte Datei")
        source_path = meta.get("source_path", "")
        snippet = r["text"][:500]
        persons = person_names_by_file.get(meta.get("file_id", ""))
        person_line = (
            f"Auf diesem Bild sind folgende Personen zu sehen: {', '.join(persons)}\n"
            if persons else ""
        )
        context_parts.append(f"[Quelle: {file_name}]\n{person_line}{snippet}")
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

    # Gesichtserkennung liefert eine gesicherte Personen-Zuordnung (Ground Truth).
    # Kleine lokale Modelle leiten aus einer Zeile im Kontext oft nicht ab, dass eine
    # Person "auf dem Bild zu sehen" ist. Daher stellen wir die Fakten explizit und
    # zusammengefasst an den Anfang des Prompts.
    person_to_files: dict[str, list[str]] = {}
    for r in retrieval_results:
        meta = r.get("metadata", {})
        for name in person_names_by_file.get(meta.get("file_id", ""), []):
            files = person_to_files.setdefault(name, [])
            fname = meta.get("file_name", "")
            if fname and fname not in files:
                files.append(fname)
    facts_block = ""
    if person_to_files:
        lines = "\n".join(
            f"- {name} ist auf folgenden Bildern zu sehen: {', '.join(files)}"
            for name, files in person_to_files.items()
        )
        facts_block = (
            "Gesicherte Fakten aus der Gesichtserkennung "
            "(verlässlich, diese Personen sind auf den genannten Bildern abgebildet):\n"
            f"{lines}\n\n"
        )

    prompt = (
        f"Benutzerfrage:\n{question}\n\n"
        f"{facts_block}"
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
