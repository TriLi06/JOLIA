from app.services.document_date_service import extract_document_date


def test_extracts_unlabelled_european_date_with_two_digit_year():
    assert extract_document_date("Vertrag geschlossen am 19.09.24") == "2024-09-19T00:00:00"


def test_extracts_unlabelled_month_and_year():
    assert extract_document_date("Abrechnung für April 2022") == "2022-04-01T00:00:00"


def test_labelled_date_takes_precedence_over_earlier_unlabelled_date():
    text = "Im Text erwähnt: 01.01.2020. Rechnungsdatum: 19.09.24"

    assert extract_document_date(text) == "2024-09-19T00:00:00"