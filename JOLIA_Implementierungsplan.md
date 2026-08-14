# JOLIA Docs – Vollständiger Implementierungsplan

**Erstellt:** 2026-06-23  
**Basis:** AI Archive Assistant Architecture & Implementation Blueprint  
**Ziel:** Turn Documents, Photos and Scans into Knowledge – vollständig lokal, ohne Cloud, ohne Docker-Zwang, ohne GPU

---

## Inhaltsverzeichnis

1. [Projektübersicht](#1-projektübersicht)
2. [Architekturüberblick](#2-architekturüberblick)
3. [Technologie-Stack](#3-technologie-stack)
4. [Projektstruktur](#4-projektstruktur)
5. [Datenbankmodell](#5-datenbankmodell)
6. [Dateiformat-Routing & Verarbeitung](#6-dateiformat-routing--verarbeitung)
7. [Ingestion-Pipeline](#7-ingestion-pipeline)
8. [Processing-Pipeline im Detail](#8-processing-pipeline-im-detail)
9. [Embedding & ChromaDB](#9-embedding--chromadb)
10. [RAG-Chat & Suche](#10-rag-chat--suche)
11. [Web-UI](#11-web-ui)
12. [Konfiguration](#12-konfiguration)
13. [Backup & Reindex](#13-backup--reindex)
14. [Implementierungsphasen (MVP-Reihenfolge)](#14-implementierungsphasen-mvp-reihenfolge)
15. [Installations- und Startskripte](#15-installations--und-startskripte)
16. [Abhängigkeiten (requirements.txt)](#16-abhängigkeiten-requirementstxt)
17. [Akzeptanzkriterien](#17-akzeptanzkriterien)

---

## 1. Projektübersicht

JOLIA Docs ist eine vollständig lokal betriebene, browserbasierende Dokumentenverwaltungslösung. Sie ermöglicht:

- **Inbox-Scanning**: Automatisches Erkennen neuer Dateien in einem konfigurierbaren Eingangsordner (z. B. NAS-Freigabe)
- **Archivierung**: Verschieben der Originaldateien in einen strukturierten `source_documents`-Ordner
- **KI-gestützte Analyse**: Extraktion von Text, Metadaten, Transkripten und Beschreibungen je nach Dateiformat
- **RAG-Datenbank**: Aufbau eines semantischen Indexes für natürlichsprachige Suche und Fragen
- **Web-UI**: Einfache, browserbasierte Oberfläche für alle Funktionen

### Unterstützte Dateiformate

| Kategorie | Formate |
|-----------|---------|
| Dokumente | `.pdf`, `.txt`, `.md`, `.docx`, `.xlsx`, `.pptx`, `.odt` |
| Gescannte / Handschriftliche Notizen | `.pdf` (Bild-PDF), `.jpg`, `.png`, `.tiff` |
| Fotos / Bilder | `.jpg`, `.jpeg`, `.png`, `.heic`, `.tiff`, `.webp` |
| Audio / Musik | `.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg` |
| Video | `.mp4`, `.mkv`, `.avi`, `.mov`, `.webm` |
| Office | `.docx`, `.xlsx`, `.pptx` |

---

## 2. Architekturüberblick

```
┌─────────────────────────────────────────────────────────┐
│                      Web Browser (LAN)                  │
└───────────────────────────┬─────────────────────────────┘
                            │ HTTP :8080
┌───────────────────────────▼─────────────────────────────┐
│               FastAPI Backend (app/main.py)             │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │  Routes  │  │ Services │  │Processors│  │  DB    │  │
│  │ /files   │  │ingestion │  │ PDF      │  │SQLite  │  │
│  │ /search  │  │embedding │  │ DOCX     │  │        │  │
│  │ /chat    │  │ rag      │  │ Image    │  │Chroma  │  │
│  │ /jobs    │  │ backup   │  │ Audio    │  │DB      │  │
│  │ /backup  │  │ reindex  │  │ Video    │  │        │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘  │
└─────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│                     Filesystem                          │
│                                                         │
│  inbox/          → Eingang (NAS oder lokal)             │
│  source_documents/ → Archiv (Originale + Sidecars)      │
│  data/archive.db → SQLite Datenbank                     │
│  data/chroma/    → ChromaDB Vektordatenbank             │
│  data/temp/      → Temporäre Konvertierungsdateien      │
└─────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│                   Externe Tools / Modelle               │
│                                                         │
│  Ollama (LLM)    → http://localhost:11434               │
│  Tesseract OCR   → Lokale Installation                  │
│  whisper.cpp     → Lokale Installation (optional)       │
│  ffmpeg          → Videoframe- und Audio-Extraktion     │
└─────────────────────────────────────────────────────────┘
```

### Kernprinzip: Filesystem als Source of Truth

```
source_documents/**/*.pdf       ← Original (unveränderlich)
source_documents/**/*.pdf.json  ← Sidecar: strukturierte Metadaten
source_documents/**/*.pdf.md    ← Sidecar: Markdown-Zusammenfassung

SQLite + ChromaDB = abgeleitete, jederzeit rekonstruierbare Indexes
```

---

## 3. Technologie-Stack

### Backend

| Komponente | Paket / Tool | Zweck |
|------------|-------------|-------|
| Web-Framework | `fastapi`, `uvicorn` | REST API + statische UI |
| Templates | `jinja2` | Server-seitiges HTML |
| Konfiguration | `python-dotenv`, `pyyaml` | `.env` + `config.yaml` |
| Validierung | `pydantic` | API-Schemas |
| Datei-Watcher | `watchdog` | Optionaler Inbox-Watcher |
| Hashing | `hashlib` (stdlib) | SHA256-Duplikaterkennung |

### Datenbanken

| Komponente | Paket | Zweck |
|------------|-------|-------|
| Metadaten | `sqlalchemy`, `alembic` + SQLite | Datei-Tracking, Status, Chunks |
| Vektordatenbank | `chromadb` | Embeddings für Semantic Search |

### Dokumentenverarbeitung

| Format | Paket | Zweck |
|--------|-------|-------|
| PDF (Text) | `pypdf` | Direkte Textextraktion |
| PDF (Bild/Scan) | `pdf2image` + Tesseract | OCR-Verarbeitung |
| DOCX | `python-docx` | Absätze und Tabellen |
| XLSX | `openpyxl` | Tabellen-Extraktion |
| PPTX | `python-pptx` | Folien-Extraktion |
| Bilder/OCR | `pillow`, `pytesseract` | Bildverarbeitung + OCR |
| EXIF-Metadaten | `pillow` (ExifTags) | GPS, Datum, Kamera |
| HEIC | `pillow-heif` | Apple HEIC-Konvertierung |

### Audio / Video

| Format | Paket / Tool | Zweck |
|--------|-------------|-------|
| Audio-Metadaten | `mutagen` | ID3-Tags, Dauer, Codec |
| Audio-Transkript | `whisper.cpp` (extern) | Spracherkennung |
| Video-Metadaten | `pymediainfo` oder `ffprobe` | Länge, Codec, Auflösung |
| Video-Frames | `ffmpeg` (extern) | Thumbnail-/Frame-Extraktion |
| Video-Audio | `ffmpeg` (extern) | Audio-Track für Transkription |

### KI / ML

| Komponente | Modell / Paket | Zweck |
|------------|---------------|-------|
| Embeddings | `sentence-transformers` | Vektorisierung von Texten |
| Embedding-Modell | `paraphrase-multilingual-MiniLM-L12-v2` | CPU-freundlich, mehrsprachig |
| LLM (RAG) | Ollama (`qwen2.5:3b` oder `mistral:7b-q4`) | Antwortgenerierung |
| OCR | Tesseract | Texterkennung aus Bildern/Scans |
| Transkription | whisper.cpp | Sprachtranskription (optional) |

---

## 4. Projektstruktur

```
jolia/
├── README.md
├── requirements.txt
├── config.example.yaml
├── .env.example
│
├── app/
│   ├── main.py                    # FastAPI App-Instanz, Startup
│   ├── config.py                  # Konfigurationsladung (yaml + .env)
│   ├── logging_config.py          # Logging-Setup
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes_files.py        # GET /files, POST /files/import
│   │   ├── routes_search.py       # GET /search
│   │   ├── routes_chat.py         # POST /chat
│   │   ├── routes_jobs.py         # GET /jobs, GET /jobs/{id}
│   │   ├── routes_backup.py       # POST /backup, GET /backup/status
│   │   └── routes_reindex.py      # POST /reindex
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py            # SQLAlchemy Engine + Session
│   │   ├── models.py              # ORM-Modelle
│   │   ├── repositories.py        # DB-Abfragen (CRUD)
│   │   └── migrations/            # Alembic Migrationen
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ingestion_service.py   # Inbox-Scan, Datei-Import-Orchestration
│   │   ├── file_type_service.py   # MIME-Erkennung, Routing-Entscheidung
│   │   ├── hashing_service.py     # SHA256-Berechnung, Duplikaterkennung
│   │   ├── archive_service.py     # Pfadberechnung, Dateiverschiebung
│   │   ├── sidecar_service.py     # JSON/MD-Sidecar-Erstellung und Lesen
│   │   ├── chunking_service.py    # Textsplitting für RAG
│   │   ├── embedding_service.py   # Modell laden, Embeddings erstellen
│   │   ├── chroma_service.py      # ChromaDB-Wrapper (CRUD auf Collections)
│   │   ├── rag_service.py         # Retrieval + Prompt-Builder + Ollama-Aufruf
│   │   ├── ollama_service.py      # HTTP-Client für Ollama API
│   │   ├── backup_service.py      # Inkrementelles Backup (rsync / Python)
│   │   └── reindex_service.py     # Rebuild-Logik (Vektor-only / Full)
│   │
│   ├── processors/
│   │   ├── __init__.py
│   │   ├── base_processor.py      # Abstract Base Class
│   │   ├── text_processor.py      # .txt, .md
│   │   ├── pdf_processor.py       # .pdf (Text + OCR-Fallback)
│   │   ├── docx_processor.py      # .docx
│   │   ├── xlsx_processor.py      # .xlsx
│   │   ├── pptx_processor.py      # .pptx
│   │   ├── image_processor.py     # .jpg, .png, .heic – EXIF + OCR
│   │   ├── audio_processor.py     # .mp3, .wav, .m4a – Mutagen + Whisper
│   │   ├── video_processor.py     # .mp4, .mkv – ffprobe + Frame + Whisper
│   │   └── generic_processor.py   # Fallback für unbekannte Typen
│   │
│   ├── templates/
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── search.html
│   │   ├── chat.html
│   │   ├── file_detail.html
│   │   ├── jobs.html
│   │   └── settings.html
│   │
│   └── static/
│       ├── styles.css
│       └── app.js
│
├── scripts/
│   ├── run_dev_windows.ps1
│   ├── run_linux.sh
│   └── install_linux.sh
│
└── tests/
    ├── test_chunking.py
    ├── test_hashing.py
    ├── test_sidecars.py
    ├── test_processors.py
    └── test_reindex.py
```

---

## 5. Datenbankmodell

### 5.1 Tabelle `files`

```sql
CREATE TABLE files (
    id              TEXT PRIMARY KEY,       -- UUID
    sha256          TEXT UNIQUE NOT NULL,   -- Duplikatschutz
    original_filename TEXT NOT NULL,
    archive_path    TEXT NOT NULL,          -- Pfad in source_documents/
    sidecar_json_path TEXT,
    sidecar_md_path TEXT,
    mime_type       TEXT,
    content_type    TEXT,                   -- 'document'|'image'|'audio'|'video'|'other'
    file_size       INTEGER,
    created_at      TEXT,                   -- ISO-8601 aus Datei-Metadaten
    imported_at     TEXT NOT NULL,          -- ISO-8601 Importzeitpunkt
    processed_at    TEXT,
    status          TEXT NOT NULL,          -- siehe Statuswerte unten
    error_message   TEXT,
    tags            TEXT                    -- JSON-Array optionaler Tags
);
```

**Statuswerte:**
```
imported → queued → processing → processed
                              → failed
                              → needs_review
imported → skipped_duplicate
```

### 5.2 Tabelle `chunks`

```sql
CREATE TABLE chunks (
    id              TEXT PRIMARY KEY,       -- UUID
    file_id         TEXT NOT NULL REFERENCES files(id),
    chunk_index     INTEGER NOT NULL,
    chunk_type      TEXT,                   -- 'text'|'ocr'|'transcript'|'description'
    text            TEXT NOT NULL,
    page            INTEGER,
    section         TEXT,
    chroma_collection TEXT,
    chroma_id       TEXT,
    created_at      TEXT NOT NULL
);
```

### 5.3 Tabelle `processing_jobs`

```sql
CREATE TABLE processing_jobs (
    id              TEXT PRIMARY KEY,
    file_id         TEXT REFERENCES files(id),
    job_type        TEXT,                   -- 'ingest'|'ocr'|'embed'|'reindex'|'backup'
    status          TEXT,                   -- 'queued'|'running'|'done'|'failed'
    started_at      TEXT,
    finished_at     TEXT,
    error_message   TEXT,
    log             TEXT
);
```

### 5.4 Tabelle `backups`

```sql
CREATE TABLE backups (
    id              TEXT PRIMARY KEY,
    backup_path     TEXT,
    started_at      TEXT,
    finished_at     TEXT,
    status          TEXT,
    files_copied    INTEGER,
    bytes_copied    INTEGER,
    error_message   TEXT
);
```

### 5.5 Tabelle `app_settings`

```sql
CREATE TABLE app_settings (
    key             TEXT PRIMARY KEY,
    value           TEXT,
    updated_at      TEXT
);
```

**Gespeicherte Settings (index_meta):**
```json
{
  "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2",
  "chunking_version": "1.0",
  "ocr_engine": "tesseract",
  "pipeline_version": "1.0",
  "last_reindex_at": "2026-06-23T12:00:00"
}
```

---

## 6. Dateiformat-Routing & Verarbeitung

### 6.1 Routing-Tabelle

```python
FILE_TYPE_ROUTING = {
    # Dokumente
    "application/pdf":                              "PDFProcessor",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DocxProcessor",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":       "XlsxProcessor",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation":"PptxProcessor",
    "text/plain":                                   "TextProcessor",
    "text/markdown":                                "TextProcessor",

    # Bilder
    "image/jpeg":                                   "ImageProcessor",
    "image/png":                                    "ImageProcessor",
    "image/tiff":                                   "ImageProcessor",
    "image/heic":                                   "ImageProcessor",
    "image/webp":                                   "ImageProcessor",

    # Audio
    "audio/mpeg":                                   "AudioProcessor",
    "audio/mp4":                                    "AudioProcessor",
    "audio/wav":                                    "AudioProcessor",
    "audio/flac":                                   "AudioProcessor",
    "audio/ogg":                                    "AudioProcessor",

    # Video
    "video/mp4":                                    "VideoProcessor",
    "video/x-matroska":                             "VideoProcessor",
    "video/x-msvideo":                              "VideoProcessor",
    "video/quicktime":                              "VideoProcessor",
    "video/webm":                                   "VideoProcessor",
}
```

### 6.2 Verarbeitungsschritte je Format

#### Textdateien (.txt, .md)
```
1. Datei lesen (UTF-8)
2. Sidecar JSON erstellen (Metadaten)
3. Sidecar MD erstellen (Textinhalt)
4. Chunking
5. Embeddings erzeugen → ChromaDB
```

#### PDF-Dokumente
```
1. pypdf: Direktextraktion aller Seiten
2. Falls Text < 100 Zeichen/Seite → als Scan einordnen
3. Scan-PDF: pdf2image → PIL-Bilder → Tesseract-OCR je Seite
4. Seitentexte zusammenführen, Seitennummern merken
5. Sidecar JSON + MD erstellen
6. Chunking (seitenweise wenn möglich)
7. Embeddings → ChromaDB collection: text_chunks
```

#### DOCX-Dokumente
```
1. python-docx: alle Paragraphen + Tabellen lesen
2. Überschriften-Hierarchie erhalten
3. Tabellen als Markdown-Tabellen serialisieren
4. Sidecar JSON + MD
5. Chunking + Embeddings
```

#### XLSX-Tabellen
```
1. openpyxl: alle Sheets lesen
2. Je Sheet: Tabelleninhalt als Markdown-Tabelle
3. Sidecar JSON + MD
4. Chunking per Sheet + Embeddings
```

#### PPTX-Präsentationen
```
1. python-pptx: alle Slides lesen
2. Texte + Titelfelder je Folie extrahieren
3. Folienweise Markdown-Ausgabe
4. Sidecar JSON + MD
5. Chunking + Embeddings
```

#### Bilder / Fotos (.jpg, .png, .heic, etc.)
```
1. pillow: Bild öffnen, Auflösung, Format, Modus
2. EXIF-Extraktion: Datum, GPS-Koordinaten, Kamera, Belichtung
3. HEIC → JPEG-Konvertierung via pillow-heif (temporär)
4. pytesseract: OCR auf Bild (Sprache: deu+eng)
5. Beschreibungstext aus EXIF + OCR + Dateiname aufbauen
6. Optional: Ollama-Vision-Modell für Bildbeschreibung (wenn konfiguriert)
7. Sidecar JSON + MD mit GPS-Link wenn verfügbar
8. Embedding aus Beschreibungstext → ChromaDB collection: image_descriptions
```

#### Audio / Musik (.mp3, .wav, .m4a, .flac)
```
1. mutagen: Metadaten lesen (Artist, Album, Titel, Dauer, Bitrate)
2. Cover-Art extrahieren falls vorhanden
3. Falls whisper.cpp konfiguriert:
   a. Audio-Datei → Mono-WAV via ffmpeg (temp)
   b. whisper.cpp aufrufen, Transkript mit Zeitstempeln
   c. Temp-WAV löschen
4. Falls keine Transkription: Metadaten als Suchtext
5. Sidecar JSON + MD
6. Chunking des Transkripts / Metadaten-Text
7. Embeddings → ChromaDB collection: audio_transcripts
```

#### Video (.mp4, .mkv, .avi, .mov)
```
1. ffprobe: Videometadaten (Länge, Codec, Auflösung, Bitrate, Audio-Streams)
2. ffmpeg: Thumbnail-Frame extrahieren (bei ~10% der Dauer)
3. Thumbnail → ImageProcessor (OCR auf sichtbaren Text falls vorhanden)
4. Falls whisper.cpp konfiguriert:
   a. Audio-Track extrahieren via ffmpeg → temp WAV
   b. whisper.cpp aufrufen für Sprachtranskription
   c. Temp-Dateien löschen
5. Sidecar JSON + MD (Metadaten + Transkript)
6. Chunking des Transkripts
7. Embeddings → ChromaDB collection: audio_transcripts
8. Thumbnail-Pfad in Sidecar speichern
```

#### Handgeschriebene Notizen (Bild-PDFs oder Bilder)
```
→ Routing wie Bild oder Scan-PDF
1. OCR mit Tesseract (Vertrauen niedrig erwartet)
2. OCR-Konfidenzwert aus Tesseract-Output speichern
3. Status: needs_review wenn Konfidenz < 60%
4. UI zeigt Review-Bereich mit OCR-Ergebnis
5. Manuelle Korrektur möglich → Sidecar aktualisieren → Reembedding
```

---

## 7. Ingestion-Pipeline

### 7.1 Flussdiagramm

```
Inbox-Ordner
     │
     ▼
[1] Ordner scannen (alle Dateien)
     │
     ▼
[2] Temporäre / unvollständige Dateien ignorieren
    (z.B. .tmp, .part, ~$*)
     │
     ▼
[3] SHA256-Hash berechnen
     │
     ▼
[4] SQLite prüfen: Hash bekannt?
    ├─ JA → als skipped_duplicate markieren, weiter
    └─ NEIN → weiter
     │
     ▼
[5] MIME-Type + content_type bestimmen
     │
     ▼
[6] Ziel-Archivpfad berechnen:
    source_documents/{content_type}/{YYYY}/{YYYY-MM-DD}_{original_name}
     │
     ▼
[7] Datei in source_documents verschieben (Move, nicht Copy)
     │
     ▼
[8] SQLite-Eintrag anlegen (status=imported)
     │
     ▼
[9] Processing-Job erstellen (status=queued)
     │
     ▼
[10] Pipeline starten (status=processing)
      │
      ▼
[11] Processor ausführen (je nach Typ)
      │
      ├─ Erfolg → status=processed, Sidecars gespeichert
      └─ Fehler → status=failed, error_message gespeichert
```

### 7.2 Archivpfad-Berechnung

```python
def calculate_archive_path(filename: str, content_type: str, date: datetime) -> Path:
    year = date.strftime("%Y")
    date_prefix = date.strftime("%Y-%m-%d")
    safe_name = sanitize_filename(filename)
    return Path("source_documents") / content_type / year / f"{date_prefix}_{safe_name}"
```

Beispiele:
```
inbox/Rechnung.pdf      → source_documents/documents/2026/2026-06-23_Rechnung.pdf
inbox/IMG_001.jpg       → source_documents/images/2026/2026-06-23_IMG_001.jpg
inbox/Sprachmemo.m4a    → source_documents/audio/2026/2026-06-23_Sprachmemo.m4a
inbox/Video.mp4         → source_documents/video/2026/2026-06-23_Video.mp4
```

### 7.3 Sidecar-Format

Für jede verarbeitete Datei entstehen zwei Sidecar-Dateien:

**JSON-Sidecar** (`original.pdf.json`):
```json
{
  "file_id": "uuid",
  "original_filename": "Rechnung.pdf",
  "sha256": "abc123...",
  "mime_type": "application/pdf",
  "content_type": "document",
  "file_size": 204800,
  "processor": "PDFProcessor",
  "processor_version": "1.0",
  "pipeline_version": "1.0",
  "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2",
  "ocr_engine": "tesseract",
  "processed_at": "2026-06-23T12:00:00",
  "pages": 3,
  "word_count": 450,
  "language_detected": "de",
  "metadata": {
    "author": null,
    "creation_date": "2026-01-15"
  },
  "chunks_count": 4
}
```

**Markdown-Sidecar** (`original.pdf.md`):
```markdown
# Dokumentzusammenfassung

**Originaldatei:** Rechnung.pdf  
**Typ:** PDF-Dokument  
**Verarbeitet am:** 2026-06-23T12:00:00  

## Extrahierter Text

[Seite 1]
...extrahierter Text...

## Metadaten

- Dateigröße: 200 KB
- SHA256: abc123...
- Seitenanzahl: 3
- Wortanzahl: 450
```

---

## 8. Processing-Pipeline im Detail

### 8.1 BaseProcessor Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ProcessingResult:
    success: bool
    text: str | None
    metadata: dict
    chunks: list[dict]
    error_message: str | None = None
    needs_review: bool = False

class BaseProcessor(ABC):
    processor_version: str = "1.0"

    @abstractmethod
    def can_process(self, mime_type: str) -> bool: ...

    @abstractmethod
    def process(self, file_path: Path, file_record: dict) -> ProcessingResult: ...
```

### 8.2 Chunking-Strategie

```python
CHUNK_CONFIG = {
    "target_size": 1000,      # Zeichen
    "overlap": 150,            # Zeichen Überlapp
    "min_chunk_size": 200,     # Mindestgröße
    "preserve_headings": True  # Abschnittstitel erhalten
}
```

**Chunk-Metadaten in ChromaDB:**
```json
{
  "chunk_id": "uuid",
  "file_id": "uuid",
  "source_path": "source_documents/documents/2026/...",
  "file_name": "Rechnung.pdf",
  "content_type": "document",
  "chunk_index": 0,
  "page": 1,
  "section": "Rechnungsdetails",
  "created_year": 2026
}
```

### 8.3 Fehlerbehandlung

```
- Jeder Processor wird in try/except gekapselt
- Fehler → status=failed + error_message in SQLite
- Kein Fehler stoppt die gesamte Ingestion-Queue
- Fehlerhafte Dateien können über UI erneut verarbeitet werden
- Temporäre Dateien werden auch bei Fehler gelöscht (finally-Block)
```

---

## 9. Embedding & ChromaDB

### 9.1 Embedding-Service

```python
# Singleton-Pattern: Modell wird einmal geladen
class EmbeddingService:
    _model = None

    @classmethod
    def get_model(cls):
        if cls._model is None:
            from sentence_transformers import SentenceTransformer
            cls._model = SentenceTransformer(config.embedding_model)
        return cls._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.get_model().encode(texts, batch_size=32).tolist()
```

### 9.2 ChromaDB-Collections

| Collection | Inhalt |
|------------|--------|
| `text_chunks` | Texte aus PDF, DOCX, TXT etc. |
| `image_descriptions` | EXIF + OCR-Text aus Bildern |
| `audio_transcripts` | Whisper-Transkripte + Musikmetadaten |
| `file_summaries` | Kurzzusammenfassungen aller Dateien |

### 9.3 Idempotentes Einbetten

```python
def upsert_chunk(chunk_id: str, text: str, metadata: dict):
    """Überschreibt bestehende Chunks – kein Duplikat beim Re-Processing"""
    collection.upsert(
        ids=[chunk_id],
        embeddings=[embed(text)],
        documents=[text],
        metadatas=[metadata]
    )
```

---

## 10. RAG-Chat & Suche

### 10.1 Such-Flow

```
Benutzer: "Alle Dokumente zur Hausratversicherung"
    │
    ▼
Embedding der Anfrage (gleicher Embedding-Service)
    │
    ▼
ChromaDB: top-k=10 ähnlichste Chunks suchen
    │
    ├── Optional: SQLite FTS-Suche als Ergänzung
    │
    ▼
Ergebnisse nach Relevanz sortieren, Duplikate (gleiche Datei) zusammenführen
    │
    ▼
Rückgabe: [{ file_name, snippet, score, source_path, content_type }]
```

### 10.2 RAG-Chat-Flow

```
Benutzer: "Was steht in meiner Hausratversicherungspolice zu Wasserschäden?"
    │
    ▼
Embedding der Frage
    │
    ▼
ChromaDB: top-k=6 ähnlichste Chunks
    │
    ▼
Prompt aufbauen:
    [System-Prompt] + [Kontext-Chunks] + [Benutzerfrage]
    │
    ▼
HTTP POST → Ollama API (localhost:11434)
    │
    ▼
Antwort + Quellangaben zurückgeben
```

### 10.3 Prompt-Template

```
Du bist ein lokaler Archiv-Assistent. Beantworte die Frage des Benutzers
ausschließlich anhand der bereitgestellten Archiv-Kontexte.
Falls die Antwort nicht im Kontext enthalten ist, teile mit, dass das Archiv
keine ausreichenden Informationen enthält.
Nenne immer die Quelldateien, auf denen deine Antwort basiert.
Antworte in derselben Sprache wie der Benutzer.

Benutzerfrage:
{question}

Archiv-Kontext:
{context}

Quellen: {sources}
```

### 10.4 Ollama-Service

```python
class OllamaService:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url  # http://localhost:11434
        self.model = model         # qwen2.5:3b

    def generate(self, prompt: str) -> str:
        # POST /api/generate
        # Streaming optional
        ...

    def is_available(self) -> bool:
        # GET /api/tags prüfen
        ...
```

---

## 11. Web-UI

### 11.1 Seiten-Übersicht

| Route | Template | Funktion |
|-------|----------|----------|
| `/` | `dashboard.html` | Status, letzte Importe, Systeminfo |
| `/search` | `search.html` | Semantische Suche, Filter |
| `/chat` | `chat.html` | RAG-Chat mit Quellenangaben |
| `/files` | `files.html` | Dateiliste, Filter, Status |
| `/files/{id}` | `file_detail.html` | Detailansicht + Sidecar-Inhalte |
| `/jobs` | `jobs.html` | Processing-Jobs, Logs |
| `/settings` | `settings.html` | Konfiguration, Modell-Info |

### 11.2 Dashboard-Widgets

```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Dateien gesamt │  │  In Bearbeitung │  │   Fehlerhaft    │
│      1.234      │  │       12        │  │        3        │
└─────────────────┘  └─────────────────┘  └─────────────────┘
┌──────────────────────────────┐  ┌──────────────────────────┐
│  [ Inbox scannen ]           │  │  [ Backup starten ]      │
│  [ Reindizieren ]            │  │  Letztes Backup: gestern │
└──────────────────────────────┘  └──────────────────────────┘
┌──────────────────────────────────────────────────────────┐
│  Zuletzt importiert:                                     │
│  • 2026-06-23 Rechnung.pdf            ✓ verarbeitet      │
│  • 2026-06-22 IMG_001.jpg             ⚠ Review nötig     │
│  • 2026-06-22 Sprachmemo.m4a          ✓ verarbeitet      │
└──────────────────────────────────────────────────────────┘
```

### 11.3 Review-Funktion für Handschriften

```
Datei: Notiz_2026-06-01.jpg
OCR-Ergebnis (Konfidenz: 45%):

[Editierbares Textfeld mit OCR-Ergebnis]

[ Text korrigieren und speichern ]  → Sidecar aktualisieren + Reembedding
```

---

## 12. Konfiguration

### 12.1 config.yaml

```yaml
app:
  host: "0.0.0.0"
  port: 8080
  debug: false
  app_name: "JOLIA Docs"

paths:
  inbox: "/mnt/fritzbox/inbox"
  archive_root: "/home/docstore/source_documents"
  data_dir: "/home/docstore/data"
  temp_dir: "/home/docstore/data/temp"
  backup_target: "/mnt/external_backup/jolia_backup"

models:
  embedding_model: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
  ollama_base_url: "http://localhost:11434"
  ollama_model: "qwen2.5:3b"
  whisper_cpp_binary: ""           # leer = deaktiviert
  whisper_model_path: ""           # leer = deaktiviert
  ffmpeg_binary: "ffmpeg"          # oder absoluter Pfad

processing:
  chunk_size: 1000
  chunk_overlap: 150
  max_file_size_mb: 2000
  enable_ocr: true
  enable_audio_transcription: false
  enable_video_transcription: false
  enable_image_ocr: true
  ocr_languages: "deu+eng"
  ocr_confidence_threshold: 60     # unter diesem Wert → needs_review
  video_thumbnail_offset_pct: 10   # Prozent der Videolänge für Thumbnail

watcher:
  enabled: false
  scan_interval_seconds: 60
```

### 12.2 .env (Override für Entwicklung Windows)

```env
INBOX_PATH=C:/dev/jolia-test/inbox
ARCHIVE_ROOT=C:/dev/jolia-test/source_documents
DATA_DIR=C:/dev/jolia-test/data
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
DEBUG=true
```

### 12.3 Konfigurationsladung (config.py)

```python
from pathlib import Path
import yaml
from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()

def load_config(path: Path = Path("config.yaml")) -> AppConfig:
    with open(path) as f:
        data = yaml.safe_load(f)
    # .env-Werte überschreiben yaml-Werte
    data["paths"]["inbox"] = os.getenv("INBOX_PATH", data["paths"]["inbox"])
    ...
    return AppConfig(**data)
```

---

## 13. Backup & Reindex

### 13.1 Backup-Strategie

**Linux (bevorzugt):**
```bash
rsync -av --delete {archive_root}/ {backup_target}/source_documents/
rsync -av --delete {data_dir}/archive.db {backup_target}/data/
rsync -av --delete {data_dir}/chroma/ {backup_target}/data/chroma/
```

**Windows (Entwicklung) / Fallback:**
```python
import shutil, filecmp
# Inkrementell: nur geänderte/neue Dateien kopieren
```

### 13.2 Reindex-Modi

**Modus A: Nur Vektorindex neu aufbauen**
```
1. Alle Chroma-Collections löschen
2. Chunks aus SQLite lesen (text-Spalte)
3. Embeddings neu generieren
4. ChromaDB neu befüllen
5. index_meta in app_settings aktualisieren
```

**Modus B: Vollständiger Rebuild aus Filesystem**
```
1. SQLite-Tabellen leeren (bis auf app_settings)
2. Chroma-Collections löschen
3. source_documents/** scannen
4. Für jede Originaldatei (nicht .json, nicht .md):
   a. Sidecar-JSON lesen falls vorhanden
   b. Sonst: Datei vollständig neu verarbeiten
5. SQLite neu befüllen
6. Chunks neu einbetten
7. ChromaDB neu befüllen
```

---

## 14. Implementierungsphasen (MVP-Reihenfolge)

### Phase 1: Fundament (Woche 1)

**Ziel:** Projekt startet, DB ist angelegt, Dashboard erreichbar.

```
☐ Projektstruktur anlegen (alle Ordner + __init__.py)
☐ requirements.txt erstellen
☐ config.yaml + .env.example anlegen
☐ app/config.py – Konfigurationsladung
☐ app/logging_config.py – strukturiertes Logging
☐ app/db/database.py – SQLAlchemy-Engine + Session-Factory
☐ app/db/models.py – alle ORM-Modelle (files, chunks, jobs, backups, settings)
☐ Alembic initialisieren + erste Migration
☐ app/main.py – FastAPI-App, Startup-Events, Health-Endpoint
☐ templates/base.html + dashboard.html (minimales HTML)
☐ scripts/run_dev_windows.ps1
☐ Test: App startet, DB wird angelegt, /health gibt 200 zurück
```

### Phase 2: Datei-Import (Woche 1–2)

**Ziel:** Dateien können aus Inbox ins Archiv importiert werden.

```
☐ app/services/hashing_service.py – SHA256 + Duplikaterkennung
☐ app/services/file_type_service.py – MIME + content_type-Erkennung
☐ app/services/archive_service.py – Pfadberechnung + Dateiverschiebung
☐ app/services/ingestion_service.py – Orchestration des Import-Flows
☐ app/api/routes_files.py – POST /files/import-inbox, GET /files
☐ app/db/repositories.py – CRUD für files + jobs
☐ Dashboard: "Inbox scannen"-Button mit Ergebnis-Feedback
☐ Test: Datei in Inbox → erscheint in source_documents + SQLite-Eintrag
```

### Phase 3: Text- und PDF-Verarbeitung (Woche 2)

**Ziel:** Textdokumente werden verarbeitet, Sidecars erzeugt, Chunks in SQLite.

```
☐ app/processors/base_processor.py – ABC + ProcessingResult
☐ app/processors/text_processor.py – .txt + .md
☐ app/processors/pdf_processor.py – pypdf + OCR-Fallback
☐ app/services/sidecar_service.py – JSON/MD schreiben + lesen
☐ app/services/chunking_service.py – deterministisches Chunking
☐ app/api/routes_jobs.py – GET /jobs, GET /jobs/{id}
☐ templates/jobs.html – Job-Liste mit Status und Log
☐ Test: PDF → Sidecar vorhanden → Chunks in SQLite
```

### Phase 4: Embedding & semantische Suche (Woche 3)

**Ziel:** Chunks eingebettet, semantische Suche funktioniert.

```
☐ app/services/embedding_service.py – Singleton-Modell-Loader
☐ app/services/chroma_service.py – Collection-Management, upsert, query
☐ app/api/routes_search.py – GET /search?q=...
☐ templates/search.html – Sucheingabe + Ergebnisliste mit Snippets
☐ Integration in ingestion_service: nach Chunking → Embeddings → Chroma
☐ Test: Dokument importieren → suchen → Snippet + Quelldatei erscheint
```

### Phase 5: RAG-Chat (Woche 3–4)

**Ziel:** Natürlichsprachige Fragen werden mit Quellenangaben beantwortet.

```
☐ app/services/ollama_service.py – HTTP-Client + Verfügbarkeitscheck
☐ app/services/rag_service.py – Retrieval + Prompt-Builder + Ollama-Aufruf
☐ app/api/routes_chat.py – POST /chat
☐ templates/chat.html – Chat-Interface mit Quellenangaben
☐ Test: Frage stellen → Antwort + Quelldateien erscheinen
```

### Phase 6: Bilder & OCR (Woche 4)

**Ziel:** Fotos, Screenshots, Handschriften werden verarbeitet.

```
☐ app/processors/image_processor.py – EXIF + OCR + Beschreibungstext
☐ HEIC-Support via pillow-heif
☐ OCR-Konfidenz → needs_review wenn < threshold
☐ templates/file_detail.html – Review-Bereich für Handschriften
☐ Korrekturfunktion: Text editieren → Sidecar + Reembedding
☐ Test: Foto importieren → EXIF + OCR in Sidecar → suchbar
```

### Phase 7: Audio & Video (Woche 5)

**Ziel:** Musikdateien und Videos werden mit Metadaten erfasst, optional transkribiert.

```
☐ app/processors/audio_processor.py – Mutagen + optionaler Whisper-Aufruf
☐ app/processors/video_processor.py – ffprobe + Thumbnail + optionaler Whisper
☐ ffmpeg-Wrapper für Audio-Extraktion + Thumbnail-Erstellung
☐ Test: MP3 → Metadaten in Sidecar → suchbar nach Artist/Album
☐ Test (wenn whisper konfiguriert): M4A → Transkript in Sidecar
```

### Phase 8: Office-Dokumente (Woche 5)

**Ziel:** DOCX, XLSX, PPTX werden vollständig verarbeitet.

```
☐ app/processors/docx_processor.py
☐ app/processors/xlsx_processor.py
☐ app/processors/pptx_processor.py
☐ Test: DOCX importieren → Inhalt + Tabellen in Sidecar
```

### Phase 9: Backup & Reindex (Woche 6)

**Ziel:** Backup funktioniert, Index kann vollständig neu aufgebaut werden.

```
☐ app/services/backup_service.py – rsync + Python-Fallback
☐ app/services/reindex_service.py – Modus A + Modus B
☐ app/api/routes_backup.py + routes_reindex.py
☐ Dashboard: Backup-Button + Status + Letztes Backup
☐ Test: Backup → Dateien auf Backup-Pfad vorhanden
☐ Test: Chroma löschen → Reindex Modus A → Suche funktioniert wieder
☐ Test: DB löschen → Reindex Modus B → alles rekonstruiert
```

### Phase 10: Polish & Stabilisierung (Woche 6–7)

```
☐ templates/settings.html – Konfigurationsanzeige + Modell-Info
☐ Fehlerseiten (404, 500)
☐ Logging-Verbesserungen
☐ Automatischer Inbox-Watcher (watchdog, optional aktivierbar)
☐ scripts/install_linux.sh
☐ scripts/run_linux.sh
☐ README.md – Installations- und Betriebsanleitung
☐ Alle Tests ausführen und grün machen
```

---

## 15. Installations- und Startskripte

### 15.1 Windows Entwicklung (run_dev_windows.ps1)

```powershell
# JOLIA Docs - Windows Entwicklungsstart
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Tesseract muss separat installiert sein: https://github.com/UB-Mannheim/tesseract/wiki
# Ollama muss laufen: https://ollama.com
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

### 15.2 Linux Installation (install_linux.sh)

```bash
#!/usr/bin/env bash
set -e

echo "=== JOLIA Docs Linux Installation ==="

# System-Abhängigkeiten
sudo apt-get update
sudo apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    ffmpeg \
    python3-venv \
    python3-pip

# Optional: whisper.cpp
# echo "Whisper.cpp muss manuell kompiliert werden: https://github.com/ggerganov/whisper.cpp"

# Python-Environment
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Datenverzeichnisse anlegen
mkdir -p data/chroma data/temp source_documents

# Konfiguration
if [ ! -f config.yaml ]; then
    cp config.example.yaml config.yaml
    echo "Bitte config.yaml anpassen!"
fi

echo "=== Installation abgeschlossen ==="
echo "Starten mit: ./scripts/run_linux.sh"
```

### 15.3 Linux Start (run_linux.sh)

```bash
#!/usr/bin/env bash
set -e
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

---

## 16. Abhängigkeiten (requirements.txt)

```text
# Web-Framework
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
jinja2>=3.1.0
python-multipart>=0.0.9

# Konfiguration
pydantic>=2.7.0
pydantic-settings>=2.0.0
python-dotenv>=1.0.0
pyyaml>=6.0.0

# Datenbank
sqlalchemy>=2.0.0
alembic>=1.13.0

# Vektordatenbank
chromadb>=0.5.0

# Embeddings
sentence-transformers>=3.0.0

# Dokumentenverarbeitung
pypdf>=4.0.0
python-docx>=1.1.0
openpyxl>=3.1.0
python-pptx>=0.6.23

# Bildverarbeitung & OCR
pillow>=10.3.0
pillow-heif>=0.16.0
pytesseract>=0.3.13

# Audio-Metadaten
mutagen>=1.47.0

# Video-Metadaten (ffprobe-Wrapper)
pymediainfo>=6.1.0

# Hilfspakete
watchdog>=4.0.0
httpx>=0.27.0
```

---

## 17. Akzeptanzkriterien

Die MVP-Implementierung ist akzeptiert wenn:

| Nr. | Kriterium | Test |
|-----|-----------|------|
| 1 | App startet mit einem Befehl auf Linux | `./run_linux.sh` → kein Fehler |
| 2 | Web-UI erreichbar aus LAN-Browser | `http://<ip>:8080` → Dashboard |
| 3 | Inbox-Ordner kann manuell gescannt werden | Button → Dateien erscheinen in source_documents |
| 4 | Duplikat-Erkennung funktioniert | Gleiche Datei nochmals → skipped_duplicate |
| 5 | PDF wird zu Sidecar verarbeitet | PDF importieren → `.pdf.json` + `.pdf.md` vorhanden |
| 6 | Scan-PDF wird per OCR verarbeitet | Bild-PDF importieren → Text in Sidecar |
| 7 | Foto wird mit EXIF + OCR verarbeitet | JPG importieren → GPS + OCR in Sidecar |
| 8 | MP3 wird mit Metadaten verarbeitet | MP3 importieren → Artist/Album in Sidecar |
| 9 | Video wird mit Metadaten + Thumbnail verarbeitet | MP4 importieren → Metadaten + Thumbnail |
| 10 | Semantische Suche liefert Ergebnisse | Stichwort suchen → relevante Dateien erscheinen |
| 11 | RAG-Chat beantwortet Fragen mit Quellen | Frage → Antwort + Quelldateien |
| 12 | Backup kann ausgelöst werden | Button → Dateien auf Backup-Pfad |
| 13 | Chroma-Index kann neu aufgebaut werden | Reindex Modus A → Suche funktioniert wieder |
| 14 | Vollständiger Rebuild aus Filesystem möglich | Reindex Modus B → DB + Index rekonstruiert |
| 15 | Handschriften-Review funktioniert | Notiz importieren → Review-Bereich → Korrektur speichern |

---

## Anhang: Beispiel-Nutzerszenarien

**Szenario 1: Handgeschriebene Notiz digitalisieren**
> Benutzer legt ein Foto einer handgeschriebenen Einkaufsliste in die Inbox.  
> System importiert, erkennt Bild, führt OCR durch (Konfidenz 55% → needs_review).  
> Im Web-UI erscheint die Notiz mit OCR-Ergebnis zur Überprüfung.  
> Benutzer korrigiert den Text → Sidecar wird aktualisiert → Reembedding.  
> Notiz ist jetzt semantisch suchbar.

**Szenario 2: Versicherungsdokument finden**
> Benutzer fragt: „Welche Dokumente erwähnen meine Hausratversicherung?"  
> System findet relevante PDF-Chunks per Semantic Search.  
> Antwortet mit: „Gefunden in: Hausrat_Police_2025.pdf, Rechnung_Gebäudeversicherung.pdf"

**Szenario 3: Musiksammlung durchsuchen**
> Benutzer sucht: „Jazz Alben von Miles Davis"  
> System findet MP3-Dateien mit passendem Artist-Tag in ChromaDB (collection: audio_transcripts).

**Szenario 4: Video-Transkript durchsuchen**
> Benutzer fragt: „Wann erwähnte ich im Meeting das Budget?"  
> System sucht in Whisper-Transkripten von MP4-Dateien.  
> Antwortet mit Zeitstempel und Quelldatei.

**Szenario 5: Index nach Modellwechsel neu aufbauen**
> Benutzer wechselt Embedding-Modell in config.yaml.  
> Klickt „Reindizieren (Modus A)".  
> System löscht Chroma, generiert alle Embeddings neu.  
> Suche funktioniert weiterhin – keine Datei geht verloren.
