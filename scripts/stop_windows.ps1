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

# ── Port freiräumen ───────────────────────────────────────────────────────────
# Ein abgebrochener Start hinterlässt unter Windows gelegentlich einen
# verwaisten multiprocessing-Kindprozess, der das Socket weiterhält. In der
# Verbindungsliste steht dann noch die PID des längst beendeten Elternprozesses,
# ein Kill dieser PID hilft also nicht – der Kindprozess muss gesucht werden.
function Test-PortBusy {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

if (Test-PortBusy) {
    Write-Host "Port $Port ist noch belegt – räume auf..." -ForegroundColor Yellow

    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue } |
        ForEach-Object {
            Write-Host "  Beende PID $_ (belegt Port $Port)..." -ForegroundColor Yellow
            taskkill /PID $_ /T /F | Out-Null
        }

    # Verwaiste multiprocessing-Kinder (Elternprozess existiert nicht mehr)
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object {
            $_.CommandLine -match 'multiprocessing' -and
            -not (Get-Process -Id $_.ParentProcessId -ErrorAction SilentlyContinue)
        } |
        ForEach-Object {
            Write-Host "  Beende verwaisten Kindprozess PID $($_.ProcessId)..." -ForegroundColor Yellow
            taskkill /PID $_.ProcessId /T /F | Out-Null
        }

    # Windows gibt das Socket nicht sofort frei
    for ($i = 0; $i -lt 10 -and (Test-PortBusy); $i++) { Start-Sleep -Milliseconds 500 }
}

if (Test-PortBusy) {
    $owners = (Get-NetTCPConnection -LocalPort $Port -State Listen).OwningProcess -join ', '
    Write-Host "WARNUNG: Port $Port wird weiterhin von PID(s) $owners belegt." -ForegroundColor Red
} else {
    Write-Host "Port $Port ist frei." -ForegroundColor Green
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
