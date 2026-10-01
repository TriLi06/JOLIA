from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class TextChunk:
    chunk_index: int
    text: str
    page: int | None = None
    section: str | None = None
    chunk_type: str = "text"


def split_text(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 150,
    min_chunk_size: int = 100,
    force_single: bool = False,
) -> list[TextChunk]:
    """Teilt Text in überlappende Chunks auf.

    Sehr lange Paragraphen (ohne Leerzeilen, z.B. OCR-/Vision-Text) werden an
    Satz- und Wortgrenzen weiter zerlegt, damit kein Chunk wesentlich größer als
    chunk_size wird. force_single=True garantiert mindestens einen Chunk, auch
    wenn der Text kürzer als min_chunk_size ist (z.B. reine Metadaten bei Bildern).
    """
    if not text or not text.strip():
        return []

    # Nach Paragraphen aufteilen (doppelter Zeilenumbruch) und lange Paragraphen
    # weiter in Segmente <= chunk_size zerlegen.
    segments: list[str] = []
    for para in re.split(r"\n{2,}", text.strip()):
        para = para.strip()
        if not para:
            continue
        if len(para) <= chunk_size:
            segments.append(para)
        else:
            segments.extend(_split_long_paragraph(para, chunk_size, overlap))

    chunks: list[TextChunk] = []
    current_text = ""
    idx = 0

    for seg in segments:
        if not current_text:
            current_text = seg
        elif len(current_text) + len(seg) + 2 <= chunk_size:
            current_text = (current_text + "\n\n" + seg).strip()
        else:
            chunks.append(TextChunk(chunk_index=idx, text=current_text))
            idx += 1
            # Überlapp: letzten Teil des aktuellen Chunks behalten
            current_text = (_tail(current_text, overlap) + "\n\n" + seg).strip()

    # Letztes Stück anhängen; einen zu kleinen Rest nicht verwerfen, sondern an den
    # vorherigen Chunk anhängen (oder per force_single als eigenen Chunk behalten).
    if current_text.strip():
        if len(current_text) >= min_chunk_size:
            chunks.append(TextChunk(chunk_index=idx, text=current_text.strip()))
        elif chunks:
            prev = chunks[-1]
            chunks[-1] = TextChunk(
                chunk_index=prev.chunk_index,
                text=(prev.text + "\n\n" + current_text).strip(),
                page=prev.page,
                section=prev.section,
                chunk_type=prev.chunk_type,
            )
        elif force_single:
            chunks.append(TextChunk(chunk_index=0, text=current_text.strip()))

    # Garantiere mindestens einen Chunk, wenn gewünscht (z.B. Bild-Metadaten)
    if not chunks and force_single and text.strip():
        chunks.append(TextChunk(chunk_index=0, text=text.strip()))

    return chunks


def sample_chunk_texts(texts: list[str], max_chars: int = 6000, max_samples: int = 12) -> str:
    """Baut einen repräsentativen Kontext-Text aus vielen Chunks statt nur dem ersten.

    Bei kurzen Dokumenten werden alle Chunks verwendet. Bei sehr langen Dokumenten
    werden Chunks gleichmäßig über Anfang, Mitte und Ende verteilt ausgewählt
    (statt nur die ersten N), damit KI-Zusammenfassung/Kategorisierung auch bei
    langen Texten den gesamten Inhalt berücksichtigen, ohne dass der Prompt
    beliebig groß wird. Die Indexierung/Embeddings sind davon nicht betroffen,
    da dafür weiterhin alle Chunks einzeln verwendet werden.
    """
    non_empty = [t for t in texts if t and t.strip()]
    if not non_empty:
        return ""
    if len(non_empty) <= max_samples:
        selected = non_empty
    else:
        step = (len(non_empty) - 1) / (max_samples - 1)
        indices = sorted({round(i * step) for i in range(max_samples)})
        selected = [non_empty[i] for i in indices]
    return "\n\n".join(selected)[:max_chars]


def _split_long_paragraph(para: str, chunk_size: int, overlap: int) -> list[str]:
    """Zerlegt einen überlangen Paragraphen an Satzgrenzen (Fallback: Wortgrenzen)."""
    pieces: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+", para):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > chunk_size:
            if current:
                pieces.append(current.strip())
                current = ""
            pieces.extend(_split_by_words(sentence, chunk_size, overlap))
        elif len(current) + len(sentence) + 1 <= chunk_size:
            current = (current + " " + sentence).strip()
        else:
            if current:
                pieces.append(current.strip())
            current = (_tail(current, overlap) + " " + sentence).strip()
    if current.strip():
        pieces.append(current.strip())
    return pieces


def _split_by_words(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Harte Zerlegung an Wortgrenzen, wenn ein einzelner Satz zu lang ist."""
    pieces: list[str] = []
    current = ""
    for word in text.split():
        if len(current) + len(word) + 1 <= chunk_size:
            current = (current + " " + word).strip()
        else:
            if current:
                pieces.append(current.strip())
            current = (_tail(current, overlap) + " " + word).strip()
    if current.strip():
        pieces.append(current.strip())
    return pieces


def split_pages(
    pages: list[tuple[int, str]],
    chunk_size: int = 1000,
    overlap: int = 150,
) -> list[TextChunk]:
    """Teilt seitenweise extrahierten Text in Chunks auf. pages = [(page_no, text), ...]"""
    chunks: list[TextChunk] = []
    global_idx = 0

    for page_no, page_text in pages:
        page_chunks = split_text(page_text, chunk_size=chunk_size, overlap=overlap)
        for c in page_chunks:
            chunks.append(
                TextChunk(
                    chunk_index=global_idx,
                    text=c.text,
                    page=page_no,
                    chunk_type="text",
                )
            )
            global_idx += 1

    return chunks


def _tail(text: str, n: int) -> str:
    """Letzten n Zeichen eines Texts."""
    return text[-n:] if len(text) > n else text
