# JOLIA Docs – Container-Image (CPU-only, ohne GPU)
FROM python:3.11-slim

# Modell-Caches in ein eigenes Volume legen -> bleiben über Neustarts erhalten
# und landen NICHT im Backup von /data/store.
# HF_HOME/SENTENCE_TRANSFORMERS_HOME: Embedding-/CLAP-Modelle.
# XDG_CACHE_HOME: Whisper-Modelle landen unter $XDG_CACHE_HOME/whisper.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/cache/huggingface \
    XDG_CACHE_HOME=/cache

# System-Abhängigkeiten:
#  - OCR / Audio / Video / PDF / Medien-Metadaten
#  - libsndfile1/libglib2.0-0: librosa (CLAP) bzw. OpenCV
#  - cmake + Build-Tools + BLAS/LAPACK für dlib (Gesichtserkennung)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-deu \
        tesseract-ocr-eng \
        ffmpeg \
        poppler-utils \
        libmediainfo0v5 \
        libsndfile1 \
        libglib2.0-0 \
        cmake \
        build-essential \
        libopenblas-dev \
        liblapack-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# PyTorch bewusst ZUERST aus dem CPU-Index installieren. Sonst zieht pip die
# CUDA-Variante inkl. NVIDIA-Bibliotheken (~5 GB), die ohne GPU nutzlos ist.
RUN pip install --upgrade pip \
    && pip install --index-url https://download.pytorch.org/whl/cpu \
        torch torchvision

# Zuerst nur die Requirements kopieren -> bessere Docker-Layer-Caches.
# requirements.extra.txt aktiviert Transkription, CLIP und Gesichtserkennung.
COPY requirements.txt requirements.extra.txt ./
RUN pip install -r requirements.txt \
    && pip install -r requirements.extra.txt

# CLIP-Modell (OpenCLIP ViT-B-32) offline ins Image laden -> kein Runtime-Download
COPY scripts/ ./scripts/
RUN python scripts/download_clip_model.py ViT-B-32

# Anwendungscode + Container-Standardkonfiguration
COPY app/ ./app/
COPY config.docker.yaml ./config.yaml

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=5)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
