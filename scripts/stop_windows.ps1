# JOLIA Docs – Windows: App sicher stoppen
#
# Beendet den laufenden uvicorn-Prozessbaum (Reloader + Worker + evtl.
# Multiprocessing-Kindprozesse), ohne dass uvicorn --reload den Worker
# einfach neu startet. Ollama läuft standardmäßig weiter (persistenter
# lokaler Dienst) – mit -StopOllama kann er mitbeendet werden.

param(
    [int]$Port = 8081,
    [switch]$StopOllama
)

$ErrorActionPreference = "Stop"

Write-Host "=== JOLIA Docs – stoppen ===" -ForegroundColor Cyan

# Alle uvicorn-Prozesse der App finden (Reloader, Worker, ggf. Kinder)
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match 'app\.main:app' }

if (-not $procs) {
    Write-Host "Keine laufende uvicorn-Instanz von app.main:app gefunden." -ForegroundColor Yellow
} else {
    # Nur die obersten Prozesse beenden (taskkill /T beendet auch die Kindprozesse)
    $pids = $procs | Select-Object -ExpandProperty ProcessId
    $parentIds = $procs | Select-Object -ExpandProperty ParentProcessId
    $topLevel = $pids | Where-Object { $parentIds -notcontains $_ }
    if (-not $topLevel) { $topLevel = $pids }

    foreach ($p in $topLevel) {
        Write-Host "Beende Prozessbaum PID $p ..." -ForegroundColor Yellow
        taskkill /PID $p /T /F | Out-Null
    }
    Write-Host "JOLIA Docs gestoppt." -ForegroundColor Green
}

# Falls auf dem konfigurierten Port trotzdem noch etwas lauscht: Hinweis geben
$stillListening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($stillListening) {
    Write-Host "WARNUNG: Port $Port wird weiterhin von PID(s) $($stillListening.OwningProcess -join ', ') belegt." -ForegroundColor Red
}

if ($StopOllama) {
    $ollama = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
    if ($ollama) {
        Write-Host "Beende Ollama..." -ForegroundColor Yellow
        Stop-Process -Name "ollama" -Force
        Write-Host "Ollama gestoppt." -ForegroundColor Green
    } else {
        Write-Host "Ollama läuft nicht." -ForegroundColor Green
    }
} else {
    Write-Host "Ollama bleibt aktiv (persistenter Dienst). Mit -StopOllama auch beenden." -ForegroundColor DarkGray
}
