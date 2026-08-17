#!/usr/bin/env bash
set -e

echo "=== JOLIA Docs Linux Installation ==="

# System-Abhängigkeiten
echo "Installiere System-Pakete..."
sudo apt-get update -qq
sudo apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    ffmpeg \
    python3-venv \
    python3-pip \
    poppler-utils \
    libmediainfo-dev \
    cmake \
    build-essential \
    libopenblas-dev \
    liblapack-dev

echo "System-Pakete installiert."

# ffmpeg-Verfügbarkeit prüfen (für Audio/Video-Transkription via openai-whisper)
if command -v ffmpeg >/dev/null 2>&1; then
    echo "  ffmpeg bereits installiert."
else
    echo "  ⚠️  ffmpeg nicht gefunden – versuche erneute Installation..."
    sudo apt-get install -y ffmpeg
fi

# Tesseract prüfen (durchsuchbarer Textlayer in gescannten PDFs)
if command -v tesseract >/dev/null 2>&1; then
    echo "  Tesseract bereits installiert ($(tesseract --version 2>&1 | head -n1))."
    if ! tesseract --list-langs 2>/dev/null | grep -qx "deu"; then
        echo "  ⚠️  Deutsche Sprachdaten fehlen – installiere tesseract-ocr-deu..."
        sudo apt-get install -y tesseract-ocr-deu
    fi
else
    echo "  ⚠️  Tesseract nicht gefunden – versuche erneute Installation..."
    sudo apt-get install -y tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng
fi

# Python Virtual Environment
echo "Erstelle Python-Environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip --quiet

# ── Schritt 1: dlib + face-recognition (cmake ist bereits via apt installiert) ──
# face_recognition_models benötigt pkg_resources (aus setuptools); seit
# Python 3.12 bzw. neueren pip-Versionen wird das nicht mehr automatisch mitinstalliert.
pip install setuptools --quiet
echo "Installiere dlib und face-recognition..."
if pip install dlib face-recognition --quiet; then
    echo "  dlib + face-recognition installiert."
else
    echo "  ⚠️  dlib/face-recognition fehlgeschlagen – Gesichtserkennung nicht verfügbar."
    echo "     Zum manuellen Nachinstallieren:"
    echo "       sudo apt-get install -y cmake build-essential libopenblas-dev liblapack-dev"
    echo "       pip install dlib face-recognition"
fi

# face_recognition installiert face_recognition_models manchmal nicht zuverlässig
# von PyPI (Modelldaten-Paket, kein Wheel) – explizit prüfen und via Git nachziehen.
if ! pip show face_recognition_models >/dev/null 2>&1; then
    echo "Installiere face_recognition_models (Modelldaten)..."
    if pip install git+https://github.com/ageitgey/face_recognition_models --quiet; then
        echo "  face_recognition_models installiert."
    else
        echo "  ⚠️  face_recognition_models fehlgeschlagen – Gesichtserkennung nicht verfügbar."
    fi
else
    echo "  face_recognition_models bereits installiert."
fi

# ── Schritt 2: openai-whisper ─────────────────────────────────────────────────
echo "Installiere openai-whisper (Audio/Video-Transkription)..."
if pip install openai-whisper --quiet; then
    echo "  openai-whisper installiert."
else
    echo "  ⚠️  openai-whisper fehlgeschlagen – Transkription nicht verfügbar."
fi

# ── Schritt 3: restliche Python-Abhängigkeiten ───────────────────────────────
echo "Installiere weitere Python-Abhängigkeiten..."
grep -vE '^\s*(face-recognition|dlib|openai-whisper)' requirements.txt | pip install -r /dev/stdin --quiet

# Verzeichnisse anlegen
mkdir -p data/chroma data/temp source_documents inbox

# Konfigurationsdatei
if [ ! -f config.yaml ]; then
    cp config.example.yaml config.yaml
    echo ""
    echo "⚠️  config.yaml wurde erstellt – bitte jetzt anpassen:"
    echo "    nano config.yaml"
fi

echo ""
echo "=== Installation abgeschlossen ==="
echo ""
echo "Nächste Schritte:"
echo "  1. config.yaml anpassen (Pfade, Ollama-URL)"
echo "  2. Ollama installieren: curl -fsSL https://ollama.com/install.sh | sh"
echo "  3. LLM-Modell herunterladen: ollama pull qwen2.5:3b"
echo "  4. App starten: ./scripts/run_linux.sh"
echo ""
echo "Optional – whisper.cpp als schnelleres externes Backend:"
echo "  git clone https://github.com/ggml-org/whisper.cpp"
echo "  cd whisper.cpp && make"
echo "  bash ./models/download-ggml-model.sh small"
echo "  Dann in config.yaml: models.whisper_cpp_binary + models.whisper_model_path"
echo ""
echo "Whisper-Modellgröße (openai-whisper, in config.yaml):"
echo "  models.whisper_python_model: tiny | base | small | medium | large  (Standard: base)"
