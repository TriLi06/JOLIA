from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_client = None

COLLECTIONS = {
    "text_chunks": "text_chunks",
    "image_descriptions": "image_descriptions",
    "audio_transcripts": "audio_transcripts",
    "file_summaries": "file_summaries",
    "image_embeddings": "image_embeddings",  # Phase B: OpenCLIP visual embeddings
}


def init_chroma(chroma_dir: Path) -> None:
    global _client
    chroma_dir.mkdir(parents=True, exist_ok=True)
    import chromadb
    _client = chromadb.PersistentClient(path=str(chroma_dir))
    # Collections vorab anlegen
    for name in COLLECTIONS.values():
        _client.get_or_create_collection(name)
    logger.info("ChromaDB initialisiert: %s", chroma_dir)


def _get_collection(name: str):
    if _client is None:
        raise RuntimeError("ChromaDB nicht initialisiert. init_chroma() zuerst aufrufen.")
    return _client.get_or_create_collection(name)


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
