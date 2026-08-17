# JOLIA Docs – Windows Entwicklungsstart
# Dieses Skript richtet die Entwicklungsumgebung ein und startet die App.

$ErrorActionPreference = "Stop"

Write-Host "=== JOLIA Docs – Windows Entwicklungsstart ===" -ForegroundColor Cyan

# Virtual Environment anlegen falls nicht vorhanden
if (-Not (Test-Path ".venv")) {
    Write-Host "Erstelle virtuelles Python-Environment..." -ForegroundColor Yellow
    python -m venv .venv
}

# Aktivieren
& ".\.venv\Scripts\Activate.ps1"

# Abhängigkeiten nur installieren wenn requirements.txt sich geändert hat
$reqHash = (Get-FileHash "requirements.txt" -Algorithm MD5).Hash
$hashFile = ".venv\.req_hash"
$lastHash = if (Test-Path $hashFile) { Get-Content $hashFile } else { "" }

if ($reqHash -ne $lastHash) {
    Write-Host "Installiere Abhängigkeiten..." -ForegroundColor Yellow

    # ── Schritt 1: PyTorch (CPU) vorinstallieren wenn torch noch fehlt ───────────
    $torchOk = pip show torch 2>$null
    if (-not $torchOk) {
        Write-Host "  Installiere PyTorch (CPU-Version, ~260 MB)..." -ForegroundColor Yellow
        pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --quiet
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ⚠️  PyTorch-Installation fehlgeschlagen – versuche Standard-Install..." -ForegroundColor Yellow
            pip install torch torchvision --quiet
        }
    } else {
        Write-Host "  PyTorch bereits installiert." -ForegroundColor Green
    }

    # ── Schritt 2: dlib (vorkompiliertes Wheel, kein cmake nötig) ────────────────
    $dlibOk = pip show dlib 2>$null
    if (-not $dlibOk) {
        Write-Host "  Installiere dlib (vorkompiliertes Wheel)..." -ForegroundColor Yellow
        pip install "dlib==19.24.6" --quiet 2>$null
        if ($LASTEXITCODE -ne 0) {
            # Fallback: cmake-basierter Build
            Write-Host "  Pre-built Wheel fehlgeschlagen – versuche cmake-Build..." -ForegroundColor Yellow
            $cmakeCandidates = @(
                "$env:ProgramFiles\CMake\bin\cmake.exe",
                "${env:ProgramFiles(x86)}\CMake\bin\cmake.exe",
                "$env:ProgramFiles\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
            )
            $cmakeExe = $cmakeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
            if ($cmakeExe) { $env:PATH = "$([System.IO.Path]::GetDirectoryName($cmakeExe));$env:PATH" }
            pip install dlib --quiet 2>$null
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  ⚠️  dlib konnte nicht installiert werden." -ForegroundColor Yellow
                Write-Host "     Gesichtserkennung wird deaktiviert (App läuft normal)." -ForegroundColor DarkGray
                Write-Host "     Manuelle Installation: Visual Studio Build Tools + CMake, dann:" -ForegroundColor DarkGray
                Write-Host "       pip install dlib face-recognition" -ForegroundColor DarkGray
                $dlibOk = $false
            } else {
                $dlibOk = $true
            }
        } else {
            $dlibOk = $true
        }
    } else {
        Write-Host "  dlib bereits installiert." -ForegroundColor Green
        $dlibOk = $true
    }

    # ── Schritt 3: face-recognition (nur wenn dlib vorhanden) ────────────────────
    if ($dlibOk) {
        # face_recognition_models benötigt pkg_resources (aus setuptools); seit
        # Python 3.12 bzw. neueren pip-Versionen wird das nicht mehr automatisch mitinstalliert.
        pip install setuptools --quiet

        $frOk = pip show face-recognition 2>$null
        if (-not $frOk) {
            Write-Host "  Installiere face-recognition..." -ForegroundColor Yellow
            pip install face-recognition --quiet
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  face-recognition installiert." -ForegroundColor Green
            } else {
                Write-Host "  ⚠️  face-recognition fehlgeschlagen." -ForegroundColor Yellow
            }
        } else {
            Write-Host "  face-recognition bereits installiert." -ForegroundColor Green
        }

        # face_recognition installiert face_recognition_models manchmal nicht zuverlässig
        # von PyPI (Modelldaten-Paket, kein Wheel) – explizit prüfen und via Git nachziehen.
        $frModelsOk = pip show face_recognition_models 2>$null
        if (-not $frModelsOk) {
            Write-Host "  Installiere face_recognition_models (Modelldaten)..." -ForegroundColor Yellow
            pip install git+https://github.com/ageitgey/face_recognition_models --quiet
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  face_recognition_models installiert." -ForegroundColor Green
            } else {
                Write-Host "  ⚠️  face_recognition_models fehlgeschlagen – Gesichtserkennung nicht verfügbar." -ForegroundColor Yellow
            }
        } else {
            Write-Host "  face_recognition_models bereits installiert." -ForegroundColor Green
        }
    }

    # ── Schritt 4: openai-whisper ─────────────────────────────────────────────────
    $whisperOk = pip show openai-whisper 2>$null
    if (-not $whisperOk) {
        Write-Host "  Installiere openai-whisper (Audio/Video-Transkription)..." -ForegroundColor Yellow
        pip install openai-whisper --quiet
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  openai-whisper installiert." -ForegroundColor Green
        } else {
            Write-Host "  ⚠️  openai-whisper fehlgeschlagen – Transkription nicht verfügbar." -ForegroundColor Yellow
        }
    } else {
        Write-Host "  openai-whisper bereits installiert." -ForegroundColor Green
    }

    # ── Schritt 5: ffmpeg (für Audio/Video-Transkription via openai-whisper) ─────
    $ffmpegOk = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if (-not $ffmpegOk) {
        $wingetOk = Get-Command winget -ErrorAction SilentlyContinue
        if ($wingetOk) {
            Write-Host "  Installiere ffmpeg via winget..." -ForegroundColor Yellow
            winget install --id Gyan.FFmpeg --silent --accept-source-agreements --accept-package-agreements
            if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
                Write-Host "  ffmpeg installiert." -ForegroundColor Green
            } else {
                Write-Host "  ⚠️  ffmpeg-Installation via winget fehlgeschlagen oder erfordert einen neuen Terminal-Start." -ForegroundColor Yellow
                Write-Host "     Manuell: winget install --id Gyan.FFmpeg" -ForegroundColor DarkGray
            }
        } else {
            Write-Host "  ⚠️  winget nicht gefunden – ffmpeg konnte nicht automatisch installiert werden." -ForegroundColor Yellow
            Write-Host "     Manuell: winget install --id Gyan.FFmpeg (oder https://ffmpeg.org/download.html)" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "  ffmpeg bereits installiert." -ForegroundColor Green
    }

    # ── Schritt 5b: poppler (für PDF-Vorschaubilder via pdf2image) ──────────────
    $popplerOk = Get-Command pdftoppm -ErrorAction SilentlyContinue
    if (-not $popplerOk) {
        $wingetOk = Get-Command winget -ErrorAction SilentlyContinue
        if ($wingetOk) {
            Write-Host "  Installiere poppler via winget..." -ForegroundColor Yellow
            winget install --id oschwartz10612.Poppler --silent --accept-source-agreements --accept-package-agreements
            if (Get-Command pdftoppm -ErrorAction SilentlyContinue) {
                Write-Host "  poppler installiert." -ForegroundColor Green
            } else {
                Write-Host "  ⚠️  poppler-Installation via winget fehlgeschlagen oder erfordert einen neuen Terminal-Start." -ForegroundColor Yellow
                Write-Host "     Manuell: winget install --id oschwartz10612.Poppler (oder https://github.com/oschwartz10612/poppler-windows/releases)" -ForegroundColor DarkGray
                Write-Host "     Ohne poppler funktionieren PDF-Vorschaubilder nicht (App läuft trotzdem normal)." -ForegroundColor DarkGray
            }
        } else {
            Write-Host "  ⚠️  winget nicht gefunden – poppler konnte nicht automatisch installiert werden." -ForegroundColor Yellow
            Write-Host "     Manuell: https://github.com/oschwartz10612/poppler-windows/releases (bin-Ordner zum PATH hinzufügen)" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "  poppler bereits installiert." -ForegroundColor Green
    }

    # ── Schritt 6: restliche requirements.txt installieren ───────────────────────
    # dlib, face-recognition und openai-whisper sind bereits oben behandelt.
    # torch ebenfalls; pip überspringt bereits installierte Pakete automatisch.
    Write-Host "  Installiere verbleibende Abhängigkeiten..." -ForegroundColor Yellow
    $tempReq = [System.IO.Path]::GetTempFileName() + ".txt"
    Get-Content "requirements.txt" | Where-Object {
        $_ -notmatch '^\s*face-recognition' -and
        $_ -notmatch '^\s*dlib' -and
        $_ -notmatch '^\s*openai-whisper' -and
        $_ -notmatch '^\s*torch'
    } | Set-Content $tempReq
    pip install -r $tempReq --quiet
    Remove-Item $tempReq -Force

    if ($LASTEXITCODE -eq 0) {
        Write-Host "Alle Abhängigkeiten installiert." -ForegroundColor Green
    }

    $reqHash | Set-Content $hashFile
} else {
    Write-Host "Abhängigkeiten unverändert – überspringe Installation." -ForegroundColor Green
}

# ── Tesseract-OCR (durchsuchbarer Textlayer in gescannten PDFs) ────────────────
# Wird bei JEDEM Start geprüft, da winget-Installationen den PATH erst in einer
# neuen Shell setzen und Tesseract sonst still fehlt.
Write-Host ""
Write-Host "Prüfe Tesseract-OCR..." -ForegroundColor Cyan
$tessDirs = @(
    "$env:ProgramFiles\Tesseract-OCR",
    "${env:ProgramFiles(x86)}\Tesseract-OCR",
    "$env:LOCALAPPDATA\Programs\Tesseract-OCR"
)

function Resolve-Tesseract {
    $cmd = Get-Command tesseract -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($dir in $tessDirs) {
        $exe = Join-Path $dir "tesseract.exe"
        if (Test-Path $exe) {
            $env:PATH = "$dir;$env:PATH"
            return $exe
        }
    }
    return $null
}

$tesseractExe = Resolve-Tesseract
if (-not $tesseractExe) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "  Installiere Tesseract-OCR via winget..." -ForegroundColor Yellow
        winget install --id UB-Mannheim.TesseractOCR --silent --accept-source-agreements --accept-package-agreements
        $tesseractExe = Resolve-Tesseract
    } else {
        Write-Host "  ⚠️  winget nicht gefunden." -ForegroundColor Yellow
    }
}

if ($tesseractExe) {
    Write-Host "  Tesseract gefunden: $tesseractExe" -ForegroundColor Green
    # Deutsche Sprachdaten nachziehen, falls der Installer nur Englisch gesetzt hat
    $tessdata = Join-Path ([System.IO.Path]::GetDirectoryName($tesseractExe)) "tessdata"
    $deuData = Join-Path $tessdata "deu.traineddata"
    if ((Test-Path $tessdata) -and -not (Test-Path $deuData)) {
        Write-Host "  Lade deutsche Sprachdaten (deu.traineddata)..." -ForegroundColor Yellow
        try {
            Invoke-WebRequest -UseBasicParsing -OutFile $deuData `
                -Uri "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/deu.traineddata"
            Write-Host "  Deutsche Sprachdaten installiert." -ForegroundColor Green
        } catch {
            Write-Host "  ⚠️  Download fehlgeschlagen (Schreibrechte/Netzwerk)." -ForegroundColor Yellow
            Write-Host "     Ohne deu.traineddata in config.yaml setzen: processing.ocr_languages: `"eng`"" -ForegroundColor DarkGray
        }
    }
} else {
    Write-Host "  ⚠️  Tesseract nicht verfügbar – gescannte PDFs erhalten KEINEN markierbaren Textlayer." -ForegroundColor Yellow
    Write-Host "     Die Inhalte bleiben über die JOLIA-Suche (KI-Bildanalyse) auffindbar." -ForegroundColor DarkGray
    Write-Host "     Manuell: winget install --id UB-Mannheim.TesseractOCR" -ForegroundColor DarkGray
}

# config.yaml anlegen falls nicht vorhanden
if (-Not (Test-Path "config.yaml")) {
    Copy-Item "config.example.yaml" "config.yaml"
    Write-Host "config.yaml erstellt – bitte anpassen!" -ForegroundColor Yellow
}

# .env anlegen falls nicht vorhanden
if (-Not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env erstellt – bitte Pfade anpassen!" -ForegroundColor Yellow
}

# Testverzeichnisse anlegen
New-Item -ItemType Directory -Force -Path "C:\dev\jolia-test\inbox" | Out-Null
New-Item -ItemType Directory -Force -Path "C:\dev\jolia-test\source_documents" | Out-Null
New-Item -ItemType Directory -Force -Path "C:\dev\jolia-test\data" | Out-Null

Write-Host ""

# Ollama prüfen und starten
Write-Host "Prüfe Ollama..." -ForegroundColor Cyan
$ollamaRunning = $false

# ollama.exe suchen: zuerst im PATH, dann bekannte Installationsorte
$ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue)?.Source
if (-not $ollamaExe) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
        "$env:ProgramFiles\Ollama\ollama.exe",
        "C:\Ollama\ollama.exe"
    )
    $ollamaExe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

try {
    Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop | Out-Null
    $ollamaRunning = $true
    Write-Host "  Ollama läuft bereits." -ForegroundColor Green
} catch {
    Write-Host "  Ollama nicht erreichbar – versuche zu starten..." -ForegroundColor Yellow
    if ($ollamaExe) {
        Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
        Write-Host "  Warte auf Ollama..." -ForegroundColor Yellow
        $waited = 0
        do {
            Start-Sleep -Seconds 1
            $waited++
            try {
                Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null
                $ollamaRunning = $true
            } catch {}
        } while (-not $ollamaRunning -and $waited -lt 15)

        if ($ollamaRunning) {
            Write-Host "  Ollama gestartet." -ForegroundColor Green
        } else {
            Write-Host "  WARNUNG: Ollama konnte nicht gestartet werden. Embeddings werden übersprungen." -ForegroundColor Red
        }
    } else {
        Write-Host "  WARNUNG: ollama.exe nicht gefunden. Bitte installieren: https://ollama.com" -ForegroundColor Red
    }
}

# Ollama-Modelle sicherstellen
if ($ollamaRunning -and $ollamaExe) {
    $modelsJson = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing | ConvertFrom-Json
    $installedModels = $modelsJson.models | ForEach-Object { $_.name }

    foreach ($model in @("qwen2.5:1.5b", "nomic-embed-text", "moondream")) {
        if ($installedModels -notcontains $model) {
            Write-Host "  Lade Modell: $model ..." -ForegroundColor Yellow
            & $ollamaExe pull $model
        } else {
            Write-Host "  Modell vorhanden: $model" -ForegroundColor Green
        }
    }
}

Write-Host ""
Write-Host "Starte JOLIA Docs auf http://127.0.0.1:8081 ..." -ForegroundColor Green

# --reload-dir app: nur Änderungen im app/-Verzeichnis triggern einen Neustart
# (nicht Datenbankdateien, Logs oder andere Daten)
uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8081
