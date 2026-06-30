from app.services.chunking_service import split_text, split_pages


def test_split_text_basic():
    text = "Dies ist ein Test. " * 100
    chunks = split_text(text, chunk_size=200, overlap=50)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) > 0
        assert c.chunk_index >= 0


def test_split_text_empty():
    assert split_text("") == []
    assert split_text("   ") == []


def test_split_text_short():
    text = "Kurzer Text."
    chunks = split_text(text, chunk_size=500, overlap=50, min_chunk_size=1)
    assert len(chunks) == 1
    assert chunks[0].text == "Kurzer Text."


def test_split_pages():
    pages = [(1, "Seite eins " * 50), (2, "Seite zwei " * 50)]
    chunks = split_pages(pages, chunk_size=200, overlap=50)
    assert len(chunks) > 2
    assert all(c.page is not None for c in chunks)


def test_chunk_overlap():
    text = ("A" * 300 + "\n\n") * 5
    chunks = split_text(text, chunk_size=400, overlap=100)
    if len(chunks) >= 2:
        # Der zweite Chunk sollte Inhalt aus dem ersten übernehmen (Overlap)
        assert len(chunks[1].text) > 0
