# JOLIA Docs – Windows 11 Ein-Skript-Installation via WSL2
#
# Legt eine komplett isolierte WSL2-Distro "jolia-wsl" an (kein Docker Desktop,
# kein Microsoft-Store-Ubuntu), installiert darin Docker Engine, klont JOLIA
# und startet es per docker compose. Danach startet JOLIA bei jedem
# Windows-Login automatisch neu (Scheduled Task).
#
# Falls WSL2 auf diesem Rechner noch nicht aktiviert ist, kann ein einmaliger
# manueller Neustart nötig sein: das Skript bricht dann mit einem Hinweis ab
# und muss danach erneut ausgeführt werden.
#
# Rückstandsfreie Deinstallation: scripts\WSL_uninstall.ps1

$ErrorActionPreference = "Stop"

# ── Konfiguration ───────────────────────────────────────────────────────────
$DistroName  = "jolia-wsl"
$InstallRoot = "C:\JOLIA-WSL"
$DistroData  = Join-Path $InstallRoot "data"
$RootfsPath  = Join-Path $InstallRoot "rootfs.tar.gz"
$RepoUrl     = "https://github.com/TriLi06/JOLIA.git"
$AppDirLinux = "/opt/jolia"
$AppPort     = 8080
$TaskName    = "JOLIA-WSL-Autostart"
# Offizielle Ubuntu-WSL-Rootfs-Tarballs (für "wsl --import", kein Store-Ubuntu,
# daher keine interaktive Ersteinrichtung nötig). Erste erreichbare URL gewinnt.
$RootfsUrls = @(
    "https://cloud-images.ubuntu.com/wsl/jammy/current/ubuntu-jammy-wsl-amd64-ubuntu22.04lts.rootfs.tar.gz"
)

function Write-Step  ($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok    ($msg) { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn2 ($msg) { Write-Host "    $msg" -ForegroundColor Yellow }
function Write-Fail  ($msg) { Write-Host "    $msg" -ForegroundColor Red }

# ── Selbst-Elevation ────────────────────────────────────────────────────────
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Starte Skript mit Administratorrechten neu..." -ForegroundColor Yellow
    Start-Process powershell.exe -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"") -Verb RunAs
    exit 0
}

Write-Host "=== JOLIA Docs - WSL-Installation ===" -ForegroundColor Cyan

# ── Phase 1: Preflight ──────────────────────────────────────────────────────
Write-Step "Prüfe Systemvoraussetzungen..."

$build = [System.Environment]::OSVersion.Version.Build
if ($build -lt 19041) {
    Write-Fail "Windows-Build $build wird nicht unterstützt (WSL2 benötigt mindestens Build 19041)."
    exit 1
}
Write-Ok "Windows-Build $build OK."

$driveLetter = ($InstallRoot -split ":")[0]
$freeGb = [math]::Round((Get-PSDrive -Name $driveLetter).Free / 1GB, 1)
if ($freeGb -lt 15) {
    Write-Warn2 "Nur $freeGb GB frei auf Laufwerk ${driveLetter}: JOLIA + Docker-Images + KI-Modelle benötigen erfahrungsgemäß 15-20 GB. Installation läuft trotzdem weiter."
} else {
    Write-Ok "$freeGb GB frei auf Laufwerk ${driveLetter}:."
}

try {
    $null = Invoke-WebRequest -Uri "https://github.com" -Method Head -UseBasicParsing -TimeoutSec 10
    Write-Ok "Internetverbindung vorhanden."
} catch {
    Write-Warn2 "github.com nicht erreichbar. Download von Rootfs/Docker/JOLIA/KI-Modellen wird vermutlich fehlschlagen."
}

# ── Phase 2: WSL-Feature aktivieren (kein Auto-Reboot) ─────────────────────
Write-Step "Prüfe WSL2..."

function Test-WslReady {
    wsl --status *> $null
    return $LASTEXITCODE -eq 0
}

if (-not (Test-WslReady)) {
    Write-Warn2 "WSL ist noch nicht eingerichtet. Aktiviere benötigte Windows-Features..."
    dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
    dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
    Write-Host ""
    Write-Host "Die Windows-Features für WSL2 wurden aktiviert." -ForegroundColor Yellow
    Write-Host "Bitte den Rechner JETZT neu starten und dieses Skript danach erneut ausführen." -ForegroundColor Yellow
    exit 1
}
Write-Ok "WSL2 ist einsatzbereit."

wsl --set-default-version 2 | Out-Null

# ── Phase 3: Distro-Import ─────────────────────────────────────────────────
Write-Step "Prüfe JOLIA-WSL-Distro..."

# wsl -l -q liefert UTF-16-Namen mit eingebetteten Nullbytes -> vor Vergleich entfernen.
$existingDistros = (wsl -l -q) -replace "`0", ""
$distroExists = $existingDistros -contains $DistroName

if (-not $distroExists) {
    Write-Host "Lege isolierte Distro '$DistroName' an..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $DistroData -Force | Out-Null

    if (-not (Test-Path $RootfsPath)) {
        $downloaded = $false
        foreach ($url in $RootfsUrls) {
            try {
                Write-Host "  Lade Ubuntu-Rootfs von $url ..." -ForegroundColor Yellow
                Invoke-WebRequest -Uri $url -OutFile $RootfsPath -UseBasicParsing
                $downloaded = $true
                break
            } catch {
                Write-Warn2 "Download von $url fehlgeschlagen, versuche nächste Quelle..."
            }
        }
        if (-not $downloaded) {
            Write-Fail "Konnte kein Ubuntu-Rootfs herunterladen. Abbruch."
            exit 1
        }
    }

    wsl --import $DistroName $DistroData $RootfsPath --version 2
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "wsl --import fehlgeschlagen."
        exit 1
    }
    Write-Ok "Distro '$DistroName' importiert."
} else {
    Write-Ok "Distro '$DistroName' existiert bereits."
}

# ── Phase 4: Docker-Provisioning in der Distro ─────────────────────────────
Write-Step "Prüfe Docker in der Distro..."

$dockerCheck = wsl -d $DistroName -u root -- bash -c "command -v docker >/dev/null 2>&1 && echo yes || echo no"
if ($dockerCheck.Trim() -ne "yes") {
    Write-Host "Installiere Docker Engine (offizielles get.docker.com-Skript)..." -ForegroundColor Yellow
    wsl -d $DistroName -u root -- bash -c "apt-get update && apt-get install -y ca-certificates curl git && curl -fsSL https://get.docker.com | sh"
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Docker-Installation fehlgeschlagen."
        exit 1
    }
    Write-Ok "Docker Engine installiert."
} else {
    Write-Ok "Docker Engine bereits installiert."
}

# systemd wird benötigt, damit der Docker-Daemon in der Distro dauerhaft läuft.
$wslConfCheck = wsl -d $DistroName -u root -- bash -c "grep -q '^systemd=true' /etc/wsl.conf 2>/dev/null && echo yes || echo no"
if ($wslConfCheck.Trim() -ne "yes") {
    Write-Host "Aktiviere systemd in der Distro..." -ForegroundColor Yellow
    wsl -d $DistroName -u root -- bash -c "printf '[boot]\nsystemd=true\n' > /etc/wsl.conf"
    wsl --terminate $DistroName
    Start-Sleep -Seconds 3
    Write-Ok "systemd aktiviert (Distro neu gestartet)."
}

wsl -d $DistroName -u root -- bash -c "systemctl enable --now docker >/dev/null 2>&1 || service docker start" | Out-Null

# ── Phase 5: App-Deployment ─────────────────────────────────────────────────
Write-Step "Hole JOLIA-Code..."

$cloneCmd = "if [ -d $AppDirLinux/.git ]; then cd $AppDirLinux && git pull; else git clone $RepoUrl $AppDirLinux; fi"
wsl -d $DistroName -u root -- bash -c $cloneCmd
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Git-Clone/Pull fehlgeschlagen."
    Write-Warn2 "Falls das Repo privat ist: PAT direkt in der URL nutzen (https://<PAT>@github.com/...) oder vorher in der Distro Git-Credentials hinterlegen."
    exit 1
}
Write-Ok "JOLIA-Code aktuell."

# Zusätzliche Vorab-Checks, da der erste "docker compose up" mehrere GB an
# Ollama-Modellen herunterlädt (ollama-init-Dienst in docker-compose.yml).
Write-Step "Prüfe Voraussetzungen für den KI-Modell-Download..."
$freeGbNow = [math]::Round((Get-PSDrive -Name $driveLetter).Free / 1GB, 1)
if ($freeGbNow -lt 10) {
    Write-Warn2 "Nur noch $freeGbNow GB frei. Der Modell-Download (Ollama: qwen2.5:3b/7b, minicpm-v, bge-m3) benötigt ca. 10 GB und kann fehlschlagen."
} else {
    Write-Ok "$freeGbNow GB frei - ausreichend für den Modell-Download."
}
try {
    $null = Invoke-WebRequest -Uri "https://ollama.com" -Method Head -UseBasicParsing -TimeoutSec 10
    Write-Ok "ollama.com erreichbar."
} catch {
    Write-Warn2 "ollama.com nicht erreichbar - Modell-Download könnte fehlschlagen."
}

Write-Step "Starte JOLIA per Docker Compose (erster Start lädt KI-Modelle, kann dauern)..."
wsl -d $DistroName -u root -- bash -c "cd $AppDirLinux && docker compose up -d --build"
if ($LASTEXITCODE -ne 0) {
    Write-Fail "docker compose up fehlgeschlagen."
    exit 1
}

Write-Step "Warte auf JOLIA (kann beim ersten Start mehrere Minuten dauern)..."
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:$AppPort/health" -UseBasicParsing -TimeoutSec 5
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch { }
    Start-Sleep -Seconds 10
}
if ($healthy) {
    Write-Ok "JOLIA läuft."
} else {
    Write-Warn2 "JOLIA antwortet noch nicht - Modell-Download/Build läuft evtl. im Hintergrund weiter."
    Write-Warn2 "Status prüfen mit: wsl -d $DistroName -u root -- bash -c `"cd $AppDirLinux && docker compose logs -f`""
}

# ── Phase 6: Autostart bei Windows-Login ───────────────────────────────────
Write-Step "Registriere Autostart..."

$action    = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d $DistroName -u root -- bash -c `"cd $AppDirLinux && docker compose up -d`""
$trigger   = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
Write-Ok "Autostart-Task '$TaskName' registriert (startet JOLIA bei jedem Login neu)."

Write-Host ""
Write-Host "=== Fertig ===" -ForegroundColor Cyan
Write-Host "JOLIA Docs: http://localhost:$AppPort" -ForegroundColor Green
Write-Host "Deinstallation (rückstandsfrei): scripts\WSL_uninstall.ps1" -ForegroundColor DarkGray
