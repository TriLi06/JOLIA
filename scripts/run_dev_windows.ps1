# DocStoreAI – Windows Entwicklungsstart
# Dieses Skript richtet die Entwicklungsumgebung ein und startet die App.

$ErrorActionPreference = "Stop"

Write-Host "=== DocStoreAI – Windows Entwicklungsstart ===" -ForegroundColor Cyan

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

    # ── Schritt 5: restliche requirements.txt installieren ───────────────────────
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
New-Item -ItemType Directory -Force -Path "C:\dev\docstoreai-test\inbox" | Out-Null
New-Item -ItemType Directory -Force -Path "C:\dev\docstoreai-test\source_documents" | Out-Null
New-Item -ItemType Directory -Force -Path "C:\dev\docstoreai-test\data" | Out-Null

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
Write-Host "Starte DocStoreAI auf http://127.0.0.1:8081 ..." -ForegroundColor Green

# --reload-dir app: nur Änderungen im app/-Verzeichnis triggern einen Neustart
# (nicht Datenbankdateien, Logs oder andere Daten)
uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8081
