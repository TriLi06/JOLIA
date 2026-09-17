from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import Category, File
from app.services.category_service import (
    _build_file_context,
    _fallback_category_segments,
    _suggest_category_result,
    _validate_category_segments,
    assign_categories_manually,
    delete_category_subtree,
)
from app.services.category_service import _parse_category_response


def test_parse_category_pipe_response_with_explanation_in_confidence():
    assert _parse_category_response("Dokumente > Rechnungen|high (85%)") == (
        ["Dokumente", "Rechnungen"], False
    )


def test_parse_category_json_codeblock():
    response = '```json\n{"path": "Bilder > 2026", "confidence": "hoch"}\n```'
    assert _parse_category_response(response) == (["Bilder", "2026"], False)


def test_parse_category_json_create_action():
    response = '{"action":"create","path":["Dokumente","2026","Patent"],"confidence":"hoch"}'
    assert _parse_category_response(response) == (["Dokumente", "2026", "Patent"], False)


def test_validate_category_segments_requires_matching_root():
    file_record = SimpleNamespace(content_type="documents")
    assert _validate_category_segments(file_record, ["Dokumente", "2026", "Patent"]) is None
    assert _validate_category_segments(file_record, ["Bilder", "2026", "Patent"])


def test_parse_category_low_confidence_is_review():
    assert _parse_category_response("unklar|niedrig") == (None, True)


def test_file_context_contains_metadata_chunks_and_sidecars(tmp_path):
    archive_file = tmp_path / "garten.jpg"
    archive_file.write_bytes(b"image")
    (tmp_path / "garten.jpg.json").write_text('{"ocr_text": "Rose", "exif": {"Year": 2026}}', encoding="utf-8")
    (tmp_path / "garten.jpg.md").write_text("## Bildbeschreibung\nGarten mit Blumen", encoding="utf-8")
    file_record = SimpleNamespace(
        original_filename="garten.jpg", content_type="images", mime_type="image/jpeg",
        file_size=5, created_at="2026-05-01", imported_at="2026-09-16",
        sha256="abc", tags=["Garten"], user_description=None, ai_summary="Blumen im Garten",
        chunks=[SimpleNamespace(chunk_type="ocr", page=1, section=None, text="Rose")],
    )

    context = _build_file_context(file_record, "fallback", sidecar_path=archive_file)

    assert "Dateiname: garten.jpg" in context
    assert "Erstellungsdatum: 2026-05-01" in context
    assert "Tags: Garten" in context
    assert "Typ=ocr, Seite=1" in context
    assert "Bildbeschreibung" in context
    assert '"exif"' in context


def test_category_prompt_contains_full_context_and_existing_paths(monkeypatch):
    captured = {}

    class FakeOllama:
        def is_available(self):
            return True

        def generate(self, prompt):
            captured["prompt"] = prompt
            return "Bilder > 2026 > Garten|hoch"

    monkeypatch.setattr(
        "app.services.category_service._get_categorization_ollama_service",
        lambda config: FakeOllama(),
    )
    monkeypatch.setattr(
        "app.services.category_service._build_tree_paths",
        lambda db: ["Bilder > 2026", "Dokumente > Buecher > Autor"],
    )

    result = _suggest_category_result(
        object(), "DATEI\nDateiname: garten.jpg\nOCR: Rose\nKI-Zusammenfassung: Blumen", "images",
        tags=["Garten"],
    )

    assert result[0] == ["Bilder", "2026", "Garten"]
    assert "Dokumente > Buecher > Autor" in captured["prompt"]
    assert "OCR: Rose" in captured["prompt"]
    assert "drei Schritte" in captured["prompt"]
    assert "Sonstiges" in captured["prompt"]


def test_fallback_category_uses_type_year_and_abstract_default():
    file_record = SimpleNamespace(
        content_type="images", created_at=None, imported_at="2026-09-16"
    )

    assert _fallback_category_segments(file_record) == ["Bilder", "2026", "Sonstiges"]


def _category_test_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _category_test_file(file_id: str, sha256: str, category_id: str | None = None) -> File:
    return File(
        id=file_id,
        sha256=sha256,
        original_filename=f"{file_id}.pdf",
        archive_path=f"archive/{file_id}.pdf",
        category_id=category_id,
        category_assigned_by="ai" if category_id else None,
        category_needs_review=True,
        category_review_reason="Unsichere KI-Zuordnung" if category_id else None,
    )


def test_assign_categories_manually_updates_all_selected_files():
    db = _category_test_session()
    category = Category(id="category-1", name="Rechnungen")
    first_file = _category_test_file("file-1", "a" * 64)
    second_file = _category_test_file("file-2", "b" * 64)
    db.add_all([category, first_file, second_file])
    db.commit()

    assign_categories_manually(db, [first_file.id, second_file.id], category.id)

    for file_id in (first_file.id, second_file.id):
        updated = db.get(File, file_id)
        assert updated.category_id == category.id
        assert updated.category_assigned_by == "user"
        assert updated.category_needs_review is False
        assert updated.category_review_reason is None


def test_assign_categories_manually_rejects_missing_file_without_partial_update():
    db = _category_test_session()
    original_category = Category(id="category-original", name="Alt")
    target_category = Category(id="category-target", name="Neu")
    file_record = _category_test_file("file-1", "a" * 64, original_category.id)
    db.add_all([original_category, target_category, file_record])
    db.commit()

    try:
        assign_categories_manually(db, [file_record.id, "missing-file"], target_category.id)
    except ValueError as error:
        assert str(error) == "Mindestens eine Datei wurde nicht gefunden."
    else:
        raise AssertionError("Die Batch-Zuweisung muss fehlende Dateien ablehnen.")

    unchanged = db.get(File, file_record.id)
    assert unchanged.category_id == original_category.id
    assert unchanged.category_assigned_by == "ai"


def test_delete_category_subtree_moves_all_descendant_files_to_parent():
    db = _category_test_session()
    parent = Category(id="category-parent", name="Dokumente")
    category = Category(id="category-main", name="Rechnungen", parent=parent)
    child = Category(id="category-child", name="Auto", parent=category)
    direct_file = _category_test_file("file-direct", "c" * 64, category.id)
    child_file = _category_test_file("file-child", "d" * 64, child.id)
    db.add_all([parent, category, child, direct_file, child_file])
    db.commit()

    delete_category_subtree(db, category.id)

    assert db.get(Category, category.id) is None
    assert db.get(Category, child.id) is None
    for file_id in (direct_file.id, child_file.id):
        updated = db.get(File, file_id)
        assert updated.category_id == parent.id
        assert updated.category_assigned_by == "user"
        assert updated.category_needs_review is False