from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_client = None

# Ohne explizite Angabe verwendet ChromaDB als hnsw-Metrik den euklidischen
# Abstand (L2), nicht Cosinus. "score = 1 - distance" ist dann keine echte,
# über Collections hinweg vergleichbare Ähnlichkeit. Cosinus erzwingen, damit
# Scores aus unterschiedlichen Embedding-Räumen (Text, CLIP, CLAP) zumindest
# auf der gleichen Skala liegen. Wirkt nur auf neu angelegte Collections -
# bestehende erfordern eine Reindizierung (Modus A reicht).
_COLLECTION_METADATA = {"hnsw:space": "cosine"}

COLLECTIONS = {
    "text_chunks": "text_chunks",
    "image_descriptions": "image_descriptions",
    "audio_transcripts": "audio_transcripts",
    "file_summaries": "file_summaries",
    "image_embeddings": "image_embeddings",  # Phase B: OpenCLIP visual embeddings
    "audio_embeddings": "audio_embeddings",  # CLAP audio/music embeddings
}


def _repair_legacy_collection_configs(chroma_dir: Path) -> None:
    """Fix collections written by very old chromadb versions with an empty
    ('{}') config_json_str. Newer chromadb tries to parse that as a real
    configuration and crashes with KeyError('_type') instead of falling back
    to its legacy-migration path (which only triggers on NULL/empty string).
    Resetting those cells to NULL lets chromadb rebuild a valid config.
    """
    db_path = chroma_dir / "chroma.sqlite3"
    if not db_path.exists():
        return
    import sqlite3
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        cur.execute(
            "UPDATE collections SET config_json_str = NULL "
            "WHERE config_json_str = '{}'"
        )
        if cur.rowcount:
            logger.warning(
                "ChromaDB: %d Collection(s) mit leerer Legacy-Konfiguration repariert",
                cur.rowcount,
            )
        con.commit()
    except sqlite3.OperationalError:
        # Tabelle existiert (noch) nicht, z.B. bei brandneuer DB
        pass
    finally:
        con.close()


def init_chroma(chroma_dir: Path) -> None:
    global _client
    chroma_dir.mkdir(parents=True, exist_ok=True)
    _repair_legacy_collection_configs(chroma_dir)
    import chromadb
    _client = chromadb.PersistentClient(path=str(chroma_dir))
    # Collections vorab anlegen
    for name in COLLECTIONS.values():
        _client.get_or_create_collection(name, metadata=_COLLECTION_METADATA)
    logger.info("ChromaDB initialisiert: %s", chroma_dir)


def _get_collection(name: str):
    if _client is None:
        raise RuntimeError("ChromaDB nicht initialisiert. init_chroma() zuerst aufrufen.")
    return _client.get_or_create_collection(name, metadata=_COLLECTION_METADATA)


def upsert_chunks(
    collection_name: str,
    ids: list[str],
    texts: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> None:
    col = _get_collection(collection_name)
    col.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )


def query_collection(
    collection_name: str,
    query_embedding: list[float],
    n_results: int = 10,
    where: dict | None = None,
) -> list[dict]:
    col = _get_collection(collection_name)
    kwargs: dict[str, Any] = {
        "query_embeddings": [query_embedding],
        "n_results": n_results,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    results = col.query(**kwargs)
    items = []
    for i, doc_id in enumerate(results["ids"][0]):
        items.append(
            {
                "id": doc_id,
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
                "score": max(0.0, 1.0 - results["distances"][0][i]),
            }
        )
    return items


def delete_by_file_id(collection_name: str, file_id: str) -> None:
    col = _get_collection(collection_name)
    col.delete(where={"file_id": file_id})


def delete_ids(collection_name: str, ids: list[str]) -> None:
    if not ids:
        return
    col = _get_collection(collection_name)
    col.delete(ids=ids)


def delete_all(collection_name: str) -> None:
    if _client is None:
        return
    _client.delete_collection(collection_name)
    _client.get_or_create_collection(collection_name)
    logger.info("Collection geleert: %s", collection_name)


def get_collection_count(collection_name: str) -> int:
    col = _get_collection(collection_name)
    return col.count()


def get_by_ids(collection_name: str, ids: list[str]) -> dict | None:
    """Gibt Dokumente, Metadaten und Embeddings für gegebene IDs zurück."""
    try:
        col = _get_collection(collection_name)
        result = col.get(ids=ids, include=["embeddings", "documents", "metadatas"])
        return result
    except Exception as exc:
        logger.warning("get_by_ids fehlgeschlagen für %s: %s", collection_name, exc)
        return None
