"""Ermittelt das inhaltliche Erstellungs-/Belegdatum einer Datei.

- Bilder: EXIF-Aufnahmedatum (DateTimeOriginal etc.) via parse_exif_datetime().
- Dokumente: aus dem Text extrahiertes, beschriftetes Datum (z.B. Rechnungsdatum)
  via extract_document_date(). Es wird bewusst nur ein *beschriftetes* Datum
  genutzt, um nicht irgendein beliebiges Datum aus dem Fliesstext zu erraten.

Das Ergebnis dient als File.created_at (Timeline-Sortierung) - faellt auf
imported_at zurueck, wenn kein Datum gefunden wird.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

logger = logging.getLogger(__name__)

# Plausibler Zeitraum fuer erkannte Datumsangaben (schuetzt vor Fehlparsern wie Seitenzahlen)
_MIN_YEAR = 1990
_MAX_YEAR = datetime.now().year + 1

# Beschriftungen, die einem Belegdatum vorausgehen (Reihenfolge = Prioritaet)
_DATE_LABELS = [
    "rechnungsdatum",
    "belegdatum",
    "auftragsdatum",
    "ausstellungsdatum",
    "bestelldatum",
    "lieferdatum",
    "invoice date",
    "date of issue",
    "issue date",
    "order date",
    "datum",
    "date",
]

_MONTHS = {
    "januar": 1, "jan": 1, "january": 1,
    "februar": 2, "feb": 2, "february": 2,
    "maerz": 3, "märz": 3, "mar": 3, "mär": 3, "march": 3,
    "april": 4, "apr": 4,
    "mai": 5, "may": 5,
    "juni": 6, "jun": 6, "june": 6,
    "juli": 7, "jul": 7, "july": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10, "oct": 10, "october": 10,
    "november": 11, "nov": 11,
    "dezember": 12, "dez": 12, "dec": 12, "december": 12,
}

# yyyy-mm-dd (ISO)
_RE_ISO = re.compile(r"\b(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\b")
# dd.mm.yyyy / dd/mm/yyyy / dd-mm-yy (europaeisch: Tag zuerst)
_RE_DMY = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})\b")
# 12. Maerz 2024  /  12 March 2024
_RE_TEXT_DMY = re.compile(r"\b(\d{1,2})\.?\s+([A-Za-zäöüÄÖÜ]+)\.?\s+(\d{4})\b")
# March 12, 2024
_RE_TEXT_MDY = re.compile(r"\b([A-Za-zäöüÄÖÜ]+)\.?\s+(\d{1,2}),?\s+(\d{4})\b")


def _valid(y: int, m: int, d: int) -> date | None:
    if not (_MIN_YEAR <= y <= _MAX_YEAR):
        return None
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _norm_year(y: int) -> int:
    if y < 100:
        return 2000 + y if y <= (_MAX_YEAR - 2000) else 1900 + y
    return y


def _parse_date_token(text: str) -> date | None:
    """Findet das erste plausible Datum in einem kurzen Textstueck."""
    m = _RE_ISO.search(text)
    if m:
        d = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d
    m = _RE_DMY.search(text)
    if m:
        d = _valid(_norm_year(int(m.group(3))), int(m.group(2)), int(m.group(1)))
        if d:
            return d
    m = _RE_TEXT_DMY.search(text)
    if m:
        month = _MONTHS.get(m.group(2).lower())
        if month:
            d = _valid(int(m.group(3)), month, int(m.group(1)))
            if d:
                return d
    m = _RE_TEXT_MDY.search(text)
    if m:
        month = _MONTHS.get(m.group(1).lower())
        if month:
            d = _valid(int(m.group(3)), month, int(m.group(2)))
            if d:
                return d
    return None


def extract_document_date(text: str | None) -> str | None:
    """Extrahiert ein beschriftetes Belegdatum (z.B. Rechnungsdatum) aus Dokumenttext.

    Gibt eine ISO-Datetime (`YYYY-MM-DDT00:00:00`) zurueck oder None.
    """
    if not text:
        return None
    lowered = text.lower()
    for label in _DATE_LABELS:
        start = 0
        while True:
            idx = lowered.find(label, start)
            if idx == -1:
                break
            # Textstueck direkt nach der Beschriftung untersuchen (Doppelpunkt/Whitespace ueberspringen)
            window = text[idx + len(label): idx + len(label) + 40]
            d = _parse_date_token(window)
            if d:
                return f"{d.isoformat()}T00:00:00"
            start = idx + len(label)
    return None


def parse_exif_datetime(value: str | None) -> str | None:
    """Wandelt einen EXIF-Datumswert (`YYYY:MM:DD HH:MM:SS`) in eine ISO-Datetime um."""
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y:%m:%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            if _MIN_YEAR <= dt.year <= _MAX_YEAR:
                return dt.isoformat()
        except ValueError:
            continue
    return None
