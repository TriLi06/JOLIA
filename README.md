# JOLIA Docs

**Turn Documents, Photos and Scans into Knowledge.** – vollständig lokal, ohne Cloud, ohne Docker-Zwang, ohne GPU.

---

## Funktionen

- 📥 **Inbox-Import**: Automatisches Einlesen aus einem konfigurierbaren Ordner (lokal oder NAS)
- 🗂️ **Archivierung**: Strukturierte Ablage in `source_documents/` mit Datum und Typ
- 🤖 **KI-Analyse**: Extraktion von Text, Metadaten, OCR-Text und Transkripten je nach Dateiformat
- 🔍 **Semantische Suche**: Natürlichsprachige Suche über alle Inhalte via ChromaDB
- 💬 **RAG-Chat**: Fragen stellen und Antworten mit Quellenangaben erhalten (via Ollama)
- 💾 **Backup**: Inkrementelles Backup auf externe Festplatte
- 🔄 **Reindex**: Vollständiger Wiederaufbau des Index aus den Originaldateien

---

## Unterstützte Formate

| Kategorie | Formate |
|-----------|---------|
| Dokumente | PDF, TXT, MD, DOCX, XLSX, PPTX |
| Bilder / Fotos | JPG, PNG, HEIC, TIFF, WebP |
| Audio / Musik | MP3, M4A, WAV, FLAC, OGG |
| Video | MP4, MKV, AVI, MOV, WebM |

---

## Schnellstart (Windows Entwicklung)

```powershell
# 1. Repository klonen / Ordner öffnen
# 2. Voraussetzungen:
#    - Python 3.11+
#    - Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki
#    - Ollama: https://ollama.com → ollama pull qwen2.5:3b

# 3. App starten
.\scripts\run_dev_windows.ps1
```

Dann im Browser öffnen: **http://127.0.0.1:8080**

---

## Schnellstart Docker (empfohlen – ein Befehl, keine Konfiguration)

Auf einem beliebigen Linux-Rechner mit **Docker** und **Docker Compose**:

```bash
git clone <repo-url> jolia
cd jolia
docker compose up -d
```

Das war's. Beim ersten Start werden Image-Build, das LLM (`qwen2.5:3b`) und das
Embedding-Modell automatisch geladen (einmaliger Download). Danach:

- **Weboberfläche:** http://localhost:8080
- **Dateien verarbeiten:** einfach in `~/jolia/inbox` ablegen (Auto-Import)
- **Daten liegen auf dem Host unter** `~/jolia/`
  (`inbox/`, `source_documents/`, `data/`) und bleiben über Neustarts erhalten

Nützliche Befehle:

```bash
docker compose logs -f app     # Logs ansehen
docker compose down            # stoppen
docker compose up -d --build   # nach Code-Änderungen neu bauen
```

Voraussetzung auf dem Zielrechner:
```bash
curl -fsSL https://get.docker.com | sh   # Docker installieren (falls nicht vorhanden)
```

> Hinweis: CPU-only. Die erste Verarbeitung kann etwas dauern, da die Modelle
> heruntergeladen und CPU-seitig ausgeführt werden.

Im Docker-Image sind **alle Features aktiviert**: OCR, Audio-/Video-Transkription
(openai-whisper), CLIP-Bildähnlichkeitssuche (OpenCLIP, offline gebacken) und
Gesichtserkennung (face-recognition/dlib). Dadurch dauert der erste `--build`
länger (dlib wird kompiliert, ~340 MB CLIP-Modell wird geladen) und das Image ist
entsprechend groß. Die optionalen Pakete stehen in
[requirements.extra.txt](requirements.extra.txt).

---

## Installation (Linux / Deployment – ohne Docker)

```bash
# Repository klonen
git clone <repo-url> jolia
cd jolia

# Installation
bash scripts/install_linux.sh

# config.yaml anpassen
nano config.yaml

# Ollama installieren und Modell laden
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b

# Starten
bash scripts/run_linux.sh
```

---

## Konfiguration

Kopiere `config.example.yaml` nach `config.yaml` und passe die Pfade an:

```yaml
paths:
  inbox: "/mnt/fritzbox/inbox"       # Eingangsordner (NAS oder lokal)
  archive_root: "/home/docstore/source_documents"
  data_dir: "/home/docstore/data"

models:
  ollama_model: "qwen2.5:3b"          # Oder mistral:7b-instruct-q4
  embedding_model: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
```

Für die Windows-Entwicklung: `.env.example` → `.env` kopieren und anpassen.

---

## Architektur

```
Inbox-Ordner
    ↓ Import
source_documents/          ← Originaldateien (unveränderlich)
  documents/2026/...
  images/2026/...
  audio/2026/...
  video/2026/...
    + *.json               ← Sidecar: strukturierte Metadaten
    + *.md                 ← Sidecar: Markdown-Zusammenfassung

data/archive.db            ← SQLite (abgeleiteter Index)
data/chroma/               ← ChromaDB Vektoren (abgeleiteter Index)
```

**Kernprinzip**: Das Filesystem ist die Source of Truth. SQLite und ChromaDB können jederzeit aus den Originaldateien und Sidecars neu aufgebaut werden.

---

## Projektstruktur

```
app/
  main.py              FastAPI App
  config.py            Konfigurationsladung
  api/                 REST-Routes + UI-Routes
  db/                  SQLAlchemy-Modelle + Repositories
  services/            Geschäftslogik (Ingestion, Embedding, RAG, ...)
  processors/          Dateiformat-Prozessoren
  templates/           Jinja2 HTML-Templates
  static/              CSS + JavaScript
scripts/               Start- und Installationsskripte
tests/                 Unit-Tests
```

---

## Tests ausführen

```bash
source .venv/bin/activate
pip install pytest
pytest tests/ -v
```

---

## Optionale Erweiterungen

- **Audio-/Video-Transkription**: whisper.cpp installieren und in `config.yaml` konfigurieren
- **HEIC-Support**: `pip install pillow-heif` (bereits in requirements.txt)
- **Autostart Linux**: systemd-Service anlegen
- **Automatischer Inbox-Watcher**: `watcher.enabled: true` in config.yaml setzen

---

## Lizenz

Privates Projekt – kein öffentliches Release vorgesehen.
