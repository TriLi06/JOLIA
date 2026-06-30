# AI Archive Assistant – Architecture & Implementation Blueprint

**Purpose of this document:**  
This Markdown file is intended as a detailed input for GitHub Copilot / Agentic Coding. It describes the desired solution, architectural constraints, functional requirements, technical stack, folder structure, processing pipelines, data model, development guidelines and implementation priorities.

---

## 1. Project Vision

Build a local, browser-based AI archive application that can manage and search different types of personal files such as:

- PDF documents
- Office documents
- scanned documents
- handwritten notes
- images and screenshots
- audio files and music files

The application shall make all archived content searchable using AI-based indexing and retrieval. Users shall be able to ask natural language questions and receive answers based on the indexed content.

The solution is intended for local/private usage and does **not** need to fulfill enterprise-grade security, encryption, compliance or privacy requirements.

---

## 2. High-Level Goals

The application shall provide the following capabilities:

1. Import files from an inbox folder located on a FritzBox NAS.
2. Store original archived files locally on the Linux machine.
3. Extract meaningful text and metadata from each file.
4. Generate AI-friendly Markdown/JSON sidecar files next to the original file.
5. Create embeddings and store them in a local vector database.
6. Allow semantic search across documents, images and audio transcripts.
7. Allow natural-language question answering based on the indexed archive content.
8. Allow rebuilding the complete index at any time from original files and sidecars.
9. Allow backup to an external hard drive via incremental update.
10. Provide a browser-based UI accessible in the local network.
11. Be developed on Windows and deployed on Linux.
12. Run without Docker Desktop and without GPU.

---

## 3. Target Runtime Environment

### 3.1 Deployment Machine

The final application shall run on a Linux machine with the following assumptions:

```text
Operating System: Linux
CPU: Intel Core 5 class CPU
GPU: none
RAM: assume limited/consumer-grade; design for CPU-only operation
Network: local LAN access only
Storage:
  - local internal disk for archive and databases
  - optional external USB hard drive for backups
```

### 3.2 Development Environment

Development happens on a Windows machine.

Important development constraints:

```text
- Avoid Linux-only assumptions in source code where possible.
- Use pathlib instead of hardcoded path separators.
- Keep all configuration in .env or config.yaml.
- Avoid Docker as a hard requirement.
- The code shall run directly with Python virtual environments.
- The deployment target is Linux, so scripts should include Linux-friendly commands.
```

---

## 4. Architectural Constraints

The architecture shall follow these constraints:

```text
- No Docker Desktop required.
- Prefer direct Python execution using virtual environments.
- Use SQLite as metadata database.
- Use ChromaDB as local vector database.
- Use local filesystem as source of truth.
- Keep original files unchanged.
- Store generated sidecar files next to archived originals.
- CPU-only model choices.
- Browser-based UI in local network.
- Rebuild index from filesystem at any time.
```

---

## 5. Proposed Technology Stack

### 5.1 Backend

Use Python with FastAPI.

Responsibilities:

- REST API
- file listing
- search endpoint
- chat/RAG endpoint
- processing job status
- backup trigger
- reindex trigger
- configuration endpoint

Recommended packages:

```text
fastapi
uvicorn
pydantic
python-dotenv
watchdog
sqlalchemy
alembic
chromadb
sentence-transformers
pypdf
python-docx
openpyxl
pillow
mutagen
```

### 5.2 Frontend

Preferred MVP frontend:

```text
Simple local web UI served by FastAPI
```

Acceptable implementation options:

1. FastAPI + Jinja2 templates for a simple MVP.
2. FastAPI backend + React frontend for a richer UI.

For the first implementation, prefer simplicity over complexity.

MVP UI should provide:

- dashboard
- import/inbox status
- search page
- AI chat page
- file detail page
- processing job overview
- backup button
- reindex button

### 5.3 Metadata Database

Use SQLite.

Purpose:

- track files
- track processing status
- store extracted metadata
- store chunk references
- store backup status
- store processing logs

SQLite database should be stored locally, e.g.:

```text
./data/archive.db
```

### 5.4 Vector Database

Use ChromaDB local persistent storage.

Purpose:

- text embeddings
- image description embeddings
- audio transcript embeddings
- later optional image embeddings

Local path:

```text
./data/chroma/
```

Recommended Chroma collections:

```text
text_chunks
image_descriptions
audio_transcripts
file_summaries
```

For MVP, focus on text-based embeddings first.

### 5.5 AI / ML Models

Because the target machine has no GPU, use CPU-friendly setup.

#### Text embeddings

Recommended:

```text
sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

Alternative if performance is acceptable:

```text
BAAI/bge-small-en-v1.5
intfloat/multilingual-e5-small
```

Important: Choose one default CPU-friendly embedding model and make it configurable.

#### LLM for RAG answers

Preferred local runtime:

```text
Ollama
```

CPU-friendly model examples:

```text
qwen2.5:3b
qwen2.5:7b-instruct-q4
mistral:7b-instruct-q4
llama3.2:3b
```

The application should not hardcode a specific model. It should read the LLM model name and base URL from configuration.

#### OCR

For first MVP:

```text
Tesseract OCR
```

Reason: easier CPU operation and simpler installation.

Later extension:

```text
PaddleOCR
```

Use OCR for:

- scanned PDFs
- image files
- screenshots
- handwritten notes, with limited accuracy expectation

#### Image understanding

CPU-only image understanding shall be modest.

MVP approach:

- extract EXIF metadata
- OCR visible text
- generate generic image description only if a local lightweight vision model is available
- otherwise create search text from filename, OCR, EXIF and manual tags

Later extension:

- OpenCLIP for image similarity
- lightweight vision-language model if CPU performance is acceptable

#### Audio transcription

Recommended:

```text
whisper.cpp
```

The Python backend may call whisper.cpp as an external command line process.

For MVP:

- implement audio metadata extraction via Mutagen
- optionally support transcription if whisper.cpp path is configured

---

## 6. Filesystem Design

The archive should be filesystem-first.

### 6.1 Configurable Paths

All paths must be configurable:

```yaml
paths:
  inbox: "/mnt/fritzbox/inbox"
  archive_root: "/home/archive/archive"
  database_dir: "/home/archive/data"
  backup_mount: "/mnt/external_backup"
```

On Windows during development, these paths may look like:

```yaml
paths:
  inbox: "C:/dev/archive-test/inbox"
  archive_root: "C:/dev/archive-test/archive"
  database_dir: "C:/dev/archive-test/data"
  backup_mount: "E:/archive-backup"
```

Use `pathlib.Path` everywhere.

### 6.2 Archive Folder Structure

Suggested structure:

```text
archive_root/
  documents/
    2026/
      2026-06-23_invoice_example.pdf
      2026-06-23_invoice_example.json
      2026-06-23_invoice_example.md

  images/
    2026/
      2026-06-23_photo_example.jpg
      2026-06-23_photo_example.json
      2026-06-23_photo_example.md

  audio/
    2026/
      2026-06-23_voice_note.m4a
      2026-06-23_voice_note.json
      2026-06-23_voice_note.md

  other/
    2026/
      unknown_file.bin
      unknown_file.json
```

The exact folder is derived from file type and date.

### 6.3 Sidecar Files

For each original file, generate:

```text
<original_filename>.json
<original_filename>.md
```

Example:

```text
invoice.pdf
invoice.pdf.json
invoice.pdf.md
```

This makes it obvious which sidecars belong to which original file.

### 6.4 Source of Truth

The original files and sidecar files are the source of truth.

The SQLite database and ChromaDB index are derived artifacts.

This means the complete database/index can be rebuilt from:

```text
archive_root/**/*
```

---

## 7. Ingestion Concept

### 7.1 Inbox Location

The inbox folder is located on the FritzBox NAS.

Expected Linux mount example:

```text
/mnt/fritzbox/inbox
```

The application should not assume how the NAS is mounted. It only needs a configured folder path.

### 7.2 Ingestion Modes

Support two ingestion modes:

1. Manual scan/import button in UI.
2. Optional background watcher using watchdog.

For robustness, always implement manual scan first.

### 7.3 Ingestion Flow

```text
1. Scan inbox folder.
2. Detect new files.
3. Ignore temporary/partial files.
4. Calculate SHA256 hash.
5. Check if file already exists in SQLite by hash.
6. If duplicate: mark as duplicate and optionally skip.
7. Determine file type.
8. Determine target archive path.
9. Move or copy file from inbox to archive.
10. Create DB record.
11. Create processing job.
12. Start processing pipeline.
```

### 7.4 Duplicate Handling

Duplicate detection shall be based on SHA256.

If duplicate is detected:

- do not process again by default
- store duplicate event in SQLite
- show duplicate in UI

---

## 8. Processing Pipeline

Use a modular pipeline architecture.

Each processor should implement a common interface, e.g.:

```python
class BaseProcessor:
    def can_process(self, file_record) -> bool:
        ...

    def process(self, file_record) -> ProcessingResult:
        ...
```

### 8.1 Processing Status

Each file can have one of these states:

```text
imported
queued
processing
processed
failed
skipped_duplicate
needs_review
```

### 8.2 File Type Routing

Suggested routing:

```text
PDF -> DocumentProcessor
DOCX -> DocumentProcessor
XLSX -> DocumentProcessor
PPTX -> DocumentProcessor
TXT/MD -> TextProcessor
JPG/PNG/HEIC -> ImageProcessor
MP3/WAV/M4A/FLAC -> AudioProcessor
unknown -> GenericMetadataProcessor
```

---

## 9. Document Processing Requirements

### 9.1 Supported Document Types

MVP should support:

```text
.pdf
.txt
.md
.docx
.xlsx
```

Later:

```text
.pptx
.eml
.html
.odt
```

### 9.2 PDF Handling

PDF processing should:

1. Try direct text extraction.
2. If extracted text is empty or too short, mark as OCR candidate.
3. For scanned PDFs, convert pages to images and run OCR.
4. Store extracted text in Markdown sidecar.
5. Create chunks for RAG.

### 9.3 DOCX Handling

Extract paragraphs and tables.

### 9.4 XLSX Handling

Extract sheet names and cell values as structured Markdown.

### 9.5 Markdown Output Example

```markdown
# File Summary

Original file: invoice.pdf  
Detected type: PDF document  
Processed at: 2026-06-23T12:00:00  

## Extracted Text

...

## Metadata

- File size: ...
- SHA256: ...
- Pages: ...
```

---

## 10. Image Processing Requirements

Image processing should support:

```text
.jpg
.jpeg
.png
.heic, optional later
.tiff, optional later
```

MVP image processing:

1. Extract file metadata.
2. Extract EXIF metadata where available.
3. Run OCR on image to detect visible text.
4. Create Markdown summary.
5. Create embedding from generated image summary text.

Example generated image Markdown:

```markdown
# Image Summary

Original file: IMG_001.jpg

## OCR Text

Recognized text from image...

## Metadata

- Width: 4032
- Height: 3024
- Date taken: ...
- GPS: ...

## Search Text

This image file contains the following OCR text and metadata...
```

Later extensions:

- OpenCLIP embeddings
- image similarity search
- face detection and clustering
- location clustering

---

## 11. Handwritten Notes Requirements

Handwritten notes are treated like scanned images/documents.

Requirements:

1. Run OCR if possible.
2. Keep OCR confidence if available.
3. Mark output as potentially uncertain.
4. Provide UI review option.
5. Allow manual correction of extracted text.
6. Store corrected text in sidecar and re-embed after correction.

Do not assume handwriting recognition is always accurate.

---

## 12. Audio and Music Processing Requirements

Supported file types:

```text
.mp3
.wav
.m4a
.flac
.ogg, optional
```

### 12.1 Music Metadata

Use Mutagen to extract:

- title
- artist
- album
- year
- duration
- bitrate
- codec

### 12.2 Speech Transcription

If whisper.cpp is configured:

1. Convert audio if needed.
2. Run whisper.cpp.
3. Store transcript with timestamps if available.
4. Create transcript chunks.
5. Embed transcript chunks.

If whisper.cpp is not configured:

- store metadata only
- mark transcription as not available

### 12.3 Audio Markdown Example

```markdown
# Audio Summary

Original file: voice_note.m4a

## Metadata

- Duration: ...
- Format: ...
- Artist: ...

## Transcript

[00:00:01] ...
[00:00:15] ...
```

---

## 13. Chunking Strategy

Chunking should be deterministic and reproducible.

### 13.1 Text Chunking

Rules:

```text
- target chunk size: 800 to 1200 characters
- overlap: 100 to 150 characters
- preserve section headings if possible
- store source file, page, section and chunk index
```

### 13.2 Chunk Metadata

Each chunk should include:

```json
{
  "chunk_id": "...",
  "file_id": "...",
  "source_path": "...",
  "content_type": "document",
  "chunk_index": 0,
  "page": null,
  "section": null,
  "text": "..."
}
```

---

## 14. Embedding and Indexing Requirements

### 14.1 Embedding Service

Create a central embedding service.

Responsibilities:

- load configured embedding model once
- generate embeddings for chunks
- write vectors to ChromaDB
- support re-embedding during reindex

### 14.2 Chroma Collections

Minimum MVP collection:

```text
text_chunks
```

Planned collections:

```text
file_summaries
image_descriptions
audio_transcripts
```

### 14.3 Metadata Stored in Chroma

For every vector, store metadata:

```json
{
  "file_id": "...",
  "chunk_id": "...",
  "source_path": "...",
  "file_name": "...",
  "content_type": "document",
  "created_year": 2026
}
```

---

## 15. RAG / Question Answering Requirements

### 15.1 Query Flow

```text
1. User enters question.
2. Generate query embedding.
3. Retrieve top-k chunks from ChromaDB.
4. Optionally combine with SQLite full-text matching.
5. Build prompt with retrieved context.
6. Send prompt to local LLM via Ollama API.
7. Return answer with source references.
```

### 15.2 Answering Rules

The assistant must:

- answer only from retrieved context
- clearly state if answer is not found
- include source files
- include chunk/page references if available
- avoid inventing facts

### 15.3 Prompt Template

Use a prompt similar to:

```text
You are a local archive assistant. Answer the user question only using the provided archive context.
If the answer is not contained in the context, say that the archive does not contain enough information.
Always list the source files used.

User question:
{question}

Archive context:
{context}

Answer in the same language as the user.
```

---

## 16. Search Requirements

### 16.1 Search Types

MVP:

- semantic search via ChromaDB
- keyword search via SQLite FTS if feasible
- filter by file type
- filter by date/year

Later:

- image similarity
- face/person clusters
- location clusters
- audio similarity

### 16.2 Search Result Fields

Each search result should show:

- file name
- file type
- relevance score
- matching text snippet
- source path
- processed date
- link to file detail page

---

## 17. SQLite Data Model

Use SQLAlchemy models.

### 17.1 files

Fields:

```text
id
sha256
original_filename
archive_path
sidecar_json_path
sidecar_md_path
mime_type
content_type
file_size
created_at
imported_at
processed_at
status
error_message
```

### 17.2 chunks

Fields:

```text
id
file_id
chunk_index
chunk_type
text
page
section
chroma_collection
chroma_id
created_at
```

### 17.3 processing_jobs

Fields:

```text
id
file_id
job_type
status
started_at
finished_at
error_message
log
```

### 17.4 backups

Fields:

```text
id
backup_path
started_at
finished_at
status
files_copied
bytes_copied
error_message
```

### 17.5 app_settings

Fields:

```text
key
value
updated_at
```

---

## 18. Backup Requirements

### 18.1 Backup Target

An external hard drive may be connected to the Linux machine.

The backup path is configurable:

```text
/mnt/external_backup/ai_archive_backup
```

### 18.2 Backup Scope

Backup must include:

```text
archive_root/
data/archive.db
data/chroma/
config.yaml, optional
```

### 18.3 Backup Mode

Backup should be incremental.

Implementation options:

1. Python file sync using shutil/filecmp.
2. Linux rsync called from Python.

Preferred Linux implementation:

```bash
rsync -av --delete /home/archive/archive/ /mnt/external_backup/ai_archive_backup/archive/
rsync -av --delete /home/archive/data/ /mnt/external_backup/ai_archive_backup/data/
```

The UI should provide:

- backup now button
- backup status
- last backup date
- backup log

---

## 19. Reindex Requirements

Reindexing is a core requirement.

### 19.1 Reindex Use Cases

Reindex must be possible when:

- embedding model changes
- OCR logic changes
- chunking logic changes
- ChromaDB is deleted/corrupted
- SQLite database needs reconstruction

### 19.2 Reindex Modes

Support at least two modes:

#### Mode A: Rebuild vector index only

```text
- keep SQLite file records
- delete Chroma collections
- read chunks from SQLite or sidecar Markdown
- recreate embeddings
- repopulate Chroma
```

#### Mode B: Full rebuild from filesystem

```text
- scan archive_root
- identify original files
- read or recreate sidecars
- rebuild SQLite records
- recreate chunks
- recreate Chroma index
```

### 19.3 Index Versioning

Store index metadata:

```text
embedding_model_name
embedding_model_version
chunking_version
ocr_engine
processing_pipeline_version
last_reindex_at
```

---

## 20. Configuration Requirements

Use a `config.yaml` and/or `.env` file.

Example:

```yaml
app:
  host: "0.0.0.0"
  port: 8080
  debug: false

paths:
  inbox: "/mnt/fritzbox/inbox"
  archive_root: "/home/archive/archive"
  data_dir: "/home/archive/data"
  backup_target: "/mnt/external_backup/ai_archive_backup"

models:
  embedding_model: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
  ollama_base_url: "http://localhost:11434"
  ollama_model: "qwen2.5:3b"
  whisper_cpp_binary: "/usr/local/bin/whisper-cli"
  whisper_model_path: "/home/archive/models/ggml-small.bin"

processing:
  chunk_size: 1000
  chunk_overlap: 150
  max_file_size_mb: 500
  enable_ocr: true
  enable_audio_transcription: false
  enable_image_ocr: true
```

---

## 21. Local Network Web Access

FastAPI should listen on:

```text
0.0.0.0:8080
```

The application should be reachable from other devices in the LAN:

```text
http://<linux-machine-ip>:8080
```

Do not require internet access for normal operation, except initial model/package downloads.

---

## 22. Project Structure

Recommended repository structure:

```text
ai-archive-assistant/
  README.md
  requirements.txt
  config.example.yaml
  .env.example

  app/
    main.py
    config.py
    logging_config.py

    api/
      routes_files.py
      routes_search.py
      routes_chat.py
      routes_jobs.py
      routes_backup.py
      routes_reindex.py

    db/
      database.py
      models.py
      repositories.py
      migrations/

    services/
      ingestion_service.py
      file_type_service.py
      hashing_service.py
      sidecar_service.py
      chunking_service.py
      embedding_service.py
      chroma_service.py
      rag_service.py
      backup_service.py
      reindex_service.py
      ollama_service.py

    processors/
      base_processor.py
      text_processor.py
      pdf_processor.py
      docx_processor.py
      xlsx_processor.py
      image_processor.py
      audio_processor.py
      generic_processor.py

    templates/
      base.html
      dashboard.html
      search.html
      chat.html
      file_detail.html
      jobs.html

    static/
      styles.css
      app.js

  scripts/
    run_dev_windows.ps1
    run_linux.sh
    install_linux.sh
    mount_fritzbox_example.sh

  tests/
    test_chunking.py
    test_hashing.py
    test_sidecars.py
    test_reindex.py
```

---

## 23. Coding Guidelines for GitHub Copilot

### 23.1 General

- Write clean, modular Python code.
- Use type hints wherever practical.
- Use `pathlib.Path` for all file paths.
- Use Pydantic models for API schemas.
- Use SQLAlchemy for SQLite access.
- Keep processing logic separate from API routes.
- Avoid global mutable state except for controlled model/service singletons.
- Log all processing errors but never crash the whole application for one bad file.

### 23.2 Error Handling

All processors must handle exceptions and return structured error results.

Do not allow one failed file to stop the entire ingestion run.

### 23.3 Long Running Tasks

For MVP, long-running tasks can run in background threads or FastAPI background tasks.

Later, this can be replaced by a queue.

### 23.4 Model Loading

Embedding model should be loaded once and reused.

Do not reload embedding model per chunk.

### 23.5 Idempotency

Processing should be idempotent where possible.

If the same file is processed twice:

- do not create duplicate DB records
- do not create duplicate Chroma entries
- overwrite sidecars safely

### 23.6 Reproducibility

Generated sidecar JSON should include:

```text
processor version
model name
timestamp
source hash
```

### 23.7 UI Simplicity

The first UI should be functional and simple.

Avoid complex frontend frameworks unless explicitly needed.

---

## 24. MVP Implementation Order

Implement in this order:

### Phase 1: Foundation

```text
1. Project skeleton
2. Config loading
3. SQLite setup
4. FastAPI app
5. Basic dashboard
```

### Phase 2: File Import

```text
1. Inbox scan
2. File hashing
3. Duplicate detection
4. Archive path calculation
5. Move/copy file into archive
6. Create DB record
```

### Phase 3: Text and PDF Processing

```text
1. Text processor
2. PDF text extraction
3. Sidecar JSON/Markdown generation
4. Chunking
5. SQLite chunk storage
```

### Phase 4: Embedding and Search

```text
1. Embedding service
2. ChromaDB integration
3. Semantic search endpoint
4. Search UI
```

### Phase 5: RAG Chat

```text
1. Ollama service
2. Retrieval prompt builder
3. Chat endpoint
4. Chat UI with sources
```

### Phase 6: Images and OCR

```text
1. Image metadata extraction
2. OCR integration
3. Image sidecars
4. Index OCR text
```

### Phase 7: Audio

```text
1. Mutagen metadata extraction
2. Optional whisper.cpp integration
3. Transcript sidecars
4. Transcript indexing
```

### Phase 8: Backup and Reindex

```text
1. Backup service
2. Backup UI
3. Rebuild Chroma index
4. Full rebuild from archive_root
```

---

## 25. Non-Goals for MVP

The first version does not need:

- multi-user authentication
- encryption
- enterprise audit logging
- cloud synchronization
- Docker deployment
- GPU optimization
- perfect handwriting recognition
- perfect image understanding
- mobile app
- face recognition
- automatic document classification with high accuracy

These can be added later.

---

## 26. Acceptance Criteria for MVP

The MVP is acceptable when:

1. Application starts on Linux with one command.
2. Web UI is reachable from LAN browser.
3. Inbox folder can be scanned manually.
4. Files from inbox are imported into local archive.
5. PDF/TXT/DOCX files are processed into sidecar Markdown/JSON.
6. Extracted text is chunked and embedded into ChromaDB.
7. User can perform semantic search.
8. User can ask a question and get an answer with source references.
9. Backup to external drive can be triggered.
10. Chroma index can be rebuilt from archived files.

---

## 27. Example User Stories

### User Story 1: Import scanned document

As a user, I place a scanned PDF into the FritzBox NAS inbox.  
The system imports it, extracts text/OCR if required, creates sidecar files and makes it searchable.

### User Story 2: Ask archive question

As a user, I ask:  
"Welche Dokumente erwähnen meine Hausratversicherung?"  
The system retrieves relevant chunks and answers with source files.

### User Story 3: Backup archive

As a user, I connect an external hard drive and click "Backup now".  
The system copies only changed files and reports backup success.

### User Story 4: Reindex after model change

As a user, I change the embedding model in config.  
I trigger reindexing.  
The system rebuilds all embeddings from archived sidecars/original files.

---

## 28. Implementation Notes

### 28.1 Prefer Direct Python Execution

Do not require Docker. Installation should be possible with:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

### 28.2 Windows Development

Provide a PowerShell helper script:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

### 28.3 Linux Run Script

Provide a Linux helper script:

```bash
#!/usr/bin/env bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

### 28.4 Optional systemd Service

Later, provide a systemd unit so the app starts automatically.

---

## 29. Final Architectural Principle

The most important design rule:

```text
The archive filesystem is the source of truth.
SQLite and ChromaDB are rebuildable indexes.
```

This guarantees that model changes, index corruption or schema changes do not destroy the archive.

