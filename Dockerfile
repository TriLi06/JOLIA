# JOLIA Docs – Container-Image (CPU-only, ohne GPU)
FROM python:3.11-slim

# Modell-Caches in das gemountete Daten-Volume legen -> bleiben über Neustarts erhalten.
# HF_HOME/SENTENCE_TRANSFORMERS_HOME: Embedding-Modell.
# XDG_CACHE_HOME: Whisper-Modelle landen unter $XDG_CACHE_HOME/whisper.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/data/store/hf-cache \
    SENTENCE_TRANSFORMERS_HOME=/data/store/hf-cache \
    XDG_CACHE_HOME=/data/store/cache

# System-Abhängigkeiten:
#  - OCR / Audio / Video / PDF / Medien-Metadaten
#  - cmake + Build-Tools + BLAS/LAPACK für dlib (Gesichtserkennung)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-deu \
        tesseract-ocr-eng \
        ffmpeg \
        poppler-utils \
        libmediainfo0v5 \
        cmake \
        build-essential \
        libopenblas-dev \
        liblapack-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Zuerst nur die Requirements kopieren -> bessere Docker-Layer-Caches.
# requirements.extra.txt aktiviert Transkription, CLIP und Gesichtserkennung.
COPY requirements.txt requirements.extra.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -r requirements.extra.txt

# CLIP-Modell (OpenCLIP ViT-B-32) offline ins Image laden -> kein Runtime-Download
COPY scripts/ ./scripts/
RUN python scripts/download_clip_model.py ViT-B-32

# Anwendungscode + Container-Standardkonfiguration
COPY app/ ./app/
COPY config.docker.yaml ./config.yaml

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
