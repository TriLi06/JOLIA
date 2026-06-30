from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Config
    from app.services.chunking_service import TextChunk

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    success: bool
    chunks: list["TextChunk"] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    error_message: str | None = None
    needs_review: bool = False
    sidecar_json_path: str | None = None
    sidecar_md_path: str | None = None


class BaseProcessor(ABC):
    processor_version: str = "1.0"

    @abstractmethod
    def process(self, file_path: Path, file_record, config: "Config") -> ProcessingResult:
        ...

    def _run_vision_ollama_structured(
        self, file_path: Path, model: str, base_url: str, timeout: float
    ) -> tuple[str, str, int]:
        """Nutzt ein Ollama-Multimodal-Modell zur strukturierten Bildanalyse.

        Gibt zurück: (vision_description, ocr_text, confidence)
        Kann von ImageProcessor und VideoProcessor (Thumbnail-Analyse) genutzt werden.
        """
        try:
            from app.services.ollama_service import OllamaService
            svc = OllamaService(base_url=base_url, model=model, timeout=timeout)

            prompt = (
                "Du bist ein präziser Bildanalyse-Assistent für ein Dokumenten-Archiv. "
                "Analysiere das Bild sorgfältig und antworte vollständig auf Deutsch. "
                "Gib immer eine bestmögliche Analyse ab – auch bei unscharfen, dunklen oder "
                "schlecht beleuchteten Bildern. Verweigere niemals die Antwort und erfinde nichts, "
                "was nicht erkennbar ist.\n\n"
                "Antworte AUSSCHLIESSLICH in diesem exakten Format mit allen sechs Abschnitten:\n\n"
                "--- SZENE ---\n"
                "Beschreibe präzise in 3-5 Sätzen, was auf dem Bild zu sehen ist. "
                "Beginne mit 'Das Bild zeigt...'. Beschreibe: Art des Bildes (Foto, Screenshot, "
                "gescanntes Dokument, Grafik, Zeichnung), Innen- oder Außenaufnahme, "
                "Ort/Umgebung (z.B. Wohnzimmer, Stadtpark, Büro, Strand, Gebirge), "
                "Tageszeit, Wetter, Jahreszeit, Lichtstimmung, dominierende Farben, "
                "Bildkomposition, Perspektive und Gesamtstimmung.\n\n"
                "--- PERSONEN ---\n"
                "Anzahl der Personen als Zahl. Dann für jede Person: Geschlecht, geschätztes Alter, "
                "Kleidung, Aktivität, Position im Bild, Mimik/Emotion. Falls keine Personen: '0'\n\n"
                "--- OBJEKTE ---\n"
                "Alle erkennbaren Objekte, Fahrzeuge, Möbel, Geräte, Tiere, Pflanzen, Gebäude, "
                "Architekturdetails als kommagetrennte Liste. Sei so vollständig wie möglich.\n\n"
                "--- KATEGORIEN ---\n"
                "Wähle alle zutreffenden Kategorien aus dieser Liste (kommagetrennt): "
                "Natur, Stadt, Architektur, Innenraum, Menschen, Sport, Essen, Technologie, "
                "Fahrzeuge, Tiere, Kunst, Dokument, Screenshot, Grafik, Karte, Urkunde, "
                "Rechnung, Urlaub, Familie, Veranstaltung, Arbeit, Hobby\n\n"
                "--- TEXT ---\n"
                "Transkribiere ALLEN sichtbaren Text im Bild exakt, vollständig und zeilengetreu, "
                "einschließlich Überschriften, Absätze, Tabellen, Schilder, Aufschriften, "
                "Nummernschilder, Logos, Stempel sowie gedruckten und handgeschriebenen Text. "
                "Behalte die ursprüngliche Reihenfolge bei. Falls kein Text erkennbar ist: '(kein Text)'\n"
            )

            response = svc.describe_image(str(file_path), model=model, prompt=prompt)
            if not response.strip():
                return "", "", 0

            sections: dict[str, str] = {"SZENE": "", "PERSONEN": "", "OBJEKTE": "", "KATEGORIEN": "", "TEXT": ""}
            current = None
            for line in response.splitlines():
                stripped = line.strip()
                matched = False
                for key in sections:
                    if stripped == f"--- {key} ---":
                        current = key
                        matched = True
                        break
                if not matched and current:
                    sections[current] += line + "\n"

            scene = sections["SZENE"].strip()
            persons_text = sections["PERSONEN"].strip()
            objects_text = sections["OBJEKTE"].strip()
            categories_text = sections["KATEGORIEN"].strip()
            raw_ocr = sections["TEXT"].strip()
            ocr_text = raw_ocr if raw_ocr and raw_ocr != "(kein Text)" else ""

            description_parts = []
            if scene:
                description_parts.append(scene)
            if persons_text and persons_text != "0":
                description_parts.append(f"Personen: {persons_text}")
            if objects_text and objects_text not in ("", "(keine besonderen Objekte)"):
                description_parts.append(f"Objekte/Elemente: {objects_text}")
            if categories_text:
                description_parts.append(f"Kategorien: {categories_text}")

            if not description_parts:
                if "--- TEXT ---" in response:
                    parts = response.split("--- TEXT ---", 1)
                    desc_raw = parts[0]
                    for tag in ("--- SZENE ---", "--- PERSONEN ---", "--- OBJEKTE ---", "--- KATEGORIEN ---"):
                        desc_raw = desc_raw.replace(tag, "")
                    description_parts = [desc_raw.strip()]
                    raw_ocr2 = parts[1].strip()
                    if raw_ocr2 and raw_ocr2 != "(kein Text)":
                        ocr_text = raw_ocr2
                else:
                    description_parts = [response.strip()]

            vision_description = "\n\n".join(description_parts)
            confidence = 85 if vision_description or ocr_text else 0
            return vision_description, ocr_text, confidence

        except Exception as exc:
            logger.warning("Ollama-Vision fehlgeschlagen (%s): %s", model, exc)
            return "", "", 0
