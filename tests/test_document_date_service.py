from datetime import datetime
from types import SimpleNamespace

from app.services import document_date_service
from app.services.document_date_service import extract_audio_date, extract_document_date


def test_extracts_unlabelled_european_date_with_two_digit_year():
    assert extract_document_date("Vertrag geschlossen am 19.09.24") == "2024-09-19T00:00:00"


def test_extracts_unlabelled_month_and_year():
    assert extract_document_date("Abrechnung für April 2022") == "2022-04-01T00:00:00"


def test_labelled_date_takes_precedence_over_earlier_unlabelled_date():
    text = "Im Text erwähnt: 01.01.2020. Rechnungsdatum: 19.09.24"

    assert extract_document_date(text) == "2024-09-19T00:00:00"


def test_audio_metadata_date_takes_precedence_over_release_year():
    assert extract_audio_date({
        "year": "2001",
        "originaldate": "1979-10-26",
    }) == "1979-10-26T00:00:00"


def test_audio_metadata_year_is_accepted():
    assert extract_audio_date({"year": "1984"}) == "1984-01-01T00:00:00"


def test_earliest_file_date_uses_creation_before_modification(monkeypatch, tmp_path):
    monkeypatch.setattr(
        document_date_service.Path,
        "stat",
        lambda _path: SimpleNamespace(st_mtime=200, st_birthtime=100),
    )

    assert document_date_service.get_earliest_file_date(tmp_path / "song.mp3") == (
        datetime.fromtimestamp(100).isoformat()
    )