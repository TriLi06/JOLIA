from app.services import summarization_service


def test_summary_update_endpoint_saves_manual_text(monkeypatch):
    from app.api import routes_files

    saved = []
    monkeypatch.setattr(
        routes_files.repo,
        "get_file_by_id",
        lambda _db, _file_id: object(),
    )
    monkeypatch.setattr(
        routes_files.repo,
        "update_file_summary",
        lambda _db, file_id, summary, *, user_edited: saved.append(
            (file_id, summary, user_edited)
        ),
    )

    response = routes_files.update_file_summary(
        "file-id",
        routes_files.FileSummaryUpdate(summary="  Stundenplan 2026 Lousa  "),
        db=object(),
    )

    assert response["message"] == "Zusammenfassung gespeichert."
    assert saved == [("file-id", "Stundenplan 2026 Lousa", True)]


def test_document_summary_includes_date_context_and_returns_short_title(monkeypatch):
    prompts = []

    class Service:
        def generate(self, prompt):
            prompts.append(prompt)
            return "Stundenplan für Lousa und ihre Klasse im Schuljahr 2026/2027"

    monkeypatch.setattr(
        "app.services.ollama_service.get_background_ollama_service",
        lambda: Service(),
    )

    summary = summarization_service.generate_document_summary(
        "Stundenplan der Klasse.",
        original_filename="Scan_20261007_114900.pdf",
        document_date="2026-10-07",
    )

    assert summary == "Stundenplan für Lousa und ihre Klasse im Schuljahr 2026/2027"
    assert "Erkanntes Dokumentdatum: 2026-10-07" in prompts[0]
    assert "erfinde kein Datum" in prompts[0]


def test_document_summary_uses_original_filename_when_ai_has_no_useful_result(monkeypatch):
    class Service:
        def generate(self, _prompt):
            return "Keine Zusammenfassung möglich."

    monkeypatch.setattr(
        "app.services.ollama_service.get_background_ollama_service",
        lambda: Service(),
    )

    assert summarization_service.generate_document_summary(
        "Textinhalt", original_filename="Scan_20261007_114900.pdf"
    ) == "Scan_20261007_114900.pdf"


def test_document_summary_uses_original_filename_when_ai_fails(monkeypatch):
    class Service:
        def generate(self, _prompt):
            raise OSError("model unavailable")

    monkeypatch.setattr(
        "app.services.ollama_service.get_background_ollama_service",
        lambda: Service(),
    )

    assert summarization_service.generate_document_summary(
        "Textinhalt", original_filename="Scan_20261007_114900.pdf"
    ) == "Scan_20261007_114900.pdf"
