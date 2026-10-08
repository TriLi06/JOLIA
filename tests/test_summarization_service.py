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


def test_short_summary_update_endpoint_saves_manual_title(monkeypatch):
    from app.api import routes_files

    saved = []
    monkeypatch.setattr(
        routes_files.repo,
        "get_file_by_id",
        lambda _db, _file_id: object(),
    )
    monkeypatch.setattr(
        routes_files.repo,
        "update_file_short_summary",
        lambda _db, file_id, summary, *, user_edited: saved.append(
            (file_id, summary, user_edited)
        ),
    )

    response = routes_files.update_file_short_summary(
        "file-id",
        routes_files.FileShortSummaryUpdate(summary=" Reparatur Astra 10/2026 "),
        db=object(),
    )

    assert response["message"] == "Kurzzusammenfassung gespeichert."
    assert saved == [("file-id", "Reparatur Astra 10/2026", True)]


def test_document_description_includes_date_context(monkeypatch):
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
        document_date="2026-10-07",
    )

    assert summary == "Stundenplan für Lousa und ihre Klasse im Schuljahr 2026/2027"
    assert "Erkanntes Dokumentdatum: 2026-10-07" in prompts[0]
    assert "erfinde kein Datum" in prompts[0]


def test_short_document_summary_uses_two_to_five_words_and_keeps_date(monkeypatch):
    prompts = []

    class Service:
        def generate(self, prompt):
            prompts.append(prompt)
            return "Reparatur des Astra im Oktober 10/2026"

    monkeypatch.setattr(
        "app.services.ollama_service.get_background_ollama_service",
        lambda: Service(),
    )

    summary = summarization_service.generate_document_short_summary(
        "Reparatur Astra, 10/2026",
        original_filename="Scan_20261007_114900.pdf",
        document_date="2026-10-07",
    )

    assert summary == "Reparatur des Astra im 10/2026"
    assert 2 <= len(summary.split()) <= 5
    assert "2 bis 5 Wörter" in prompts[0]
    assert "Erkanntes Dokumentdatum: 2026-10-07" in prompts[0]


def test_document_summary_uses_original_filename_when_ai_has_no_useful_result(monkeypatch):
    class Service:
        def generate(self, _prompt):
            return "Keine Zusammenfassung möglich."

    monkeypatch.setattr(
        "app.services.ollama_service.get_background_ollama_service",
        lambda: Service(),
    )

    assert summarization_service.generate_document_summary(
        "Textinhalt"
    ) == ""


def test_document_summary_uses_original_filename_when_ai_fails(monkeypatch):
    class Service:
        def generate(self, _prompt):
            raise OSError("model unavailable")

    monkeypatch.setattr(
        "app.services.ollama_service.get_background_ollama_service",
        lambda: Service(),
    )

    assert summarization_service.generate_document_summary(
        "Textinhalt"
    ) == ""


def test_short_summary_falls_back_to_original_filename_when_ai_output_is_too_short(monkeypatch):
    class Service:
        def generate(self, _prompt):
            return "Rechnung"

    monkeypatch.setattr(
        "app.services.ollama_service.get_background_ollama_service",
        lambda: Service(),
    )

    assert summarization_service.generate_document_short_summary(
        "Rechnung für Ersatzteile",
        original_filename="Scan_20261007_114900.pdf",
    ) == "Scan_20261007_114900.pdf"
