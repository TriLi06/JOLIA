# JOLIA Docs - WSL-Testinstallation ohne Windows-Administratorrechte
#
# Legt eine eigene benutzerbezogene WSL2-Distro "jolia-wsl-test" an.
# Es werden keine Windows-Features aktiviert und kein Autostart-Task angelegt.
# WSL2 muss auf dem Rechner bereits installiert und einsatzbereit sein.
#
# Die Testinstallation liegt unter:
#   %LOCALAPPDATA%\JOLIA-WSL-test
#
# Manuell starten:
#   wsl -d jolia-wsl-test -u root -- bash -c "service docker start && cd /opt/jolia && docker compose up -d"
#
# Manuell entfernen (loescht alle Daten der Testinstallation):
#   wsl --unregister jolia-wsl-test
#   Remove-Item -Recurse -Force "$env:LOCALAPPDATA\JOLIA-WSL-test"

$ErrorActionPreference = "Stop"

$DistroName  = "jolia-wsl-test"
$InstallRoot = Join-Path $env:LOCALAPPDATA "JOLIA-WSL-test"
$DistroData  = Join-Path $InstallRoot "distro"
$RootfsPath  = Join-Path $InstallRoot "ubuntu.rootfs.tar.gz"
$RepoUrl     = "https://github.com/TriLi06/JOLIA.git"
$AppDirLinux = "/opt/jolia"
$AppPort     = 8080
$RootfsUrls  = @(
    "https://cloud-images.ubuntu.com/wsl/noble/current/ubuntu-noble-wsl-amd64-ubuntu.rootfs.tar.gz",
    "https://cloud-images.ubuntu.com/wsl/jammy/current/ubuntu-jammy-wsl-amd64-ubuntu.rootfs.tar.gz"
)

function Write-Step ($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok   ($msg) { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn ($msg) { Write-Host "    $msg" -ForegroundColor Yellow }
function Write-Fail ($msg) { Write-Host "    $msg" -ForegroundColor Red }

Write-Host "=== JOLIA Docs - WSL-Testinstallation ohne Administratorrechte ===" -ForegroundColor Cyan

Write-Step "Pruefe WSL2..."
$null = Get-Command wsl.exe -ErrorAction Stop
wsl.exe --status *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Fail "WSL2 ist nicht einsatzbereit. Bitte WSL zuerst durch einen Administrator installieren und danach dieses Script erneut ausfuehren."
    exit 1
}
Write-Ok "WSL2 ist einsatzbereit."

$existingDistros = @(
    (wsl.exe --list --quiet) -replace "`0", "" |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ }
)
$distroExists = $existingDistros -contains $DistroName

if (-not $distroExists) {
    Write-Step "Lege benutzerbezogene Distro '$DistroName' an..."
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
                Write-Warn "Download fehlgeschlagen, versuche die naechste Quelle..."
            }
        }
        if (-not $downloaded) {
            Write-Fail "Konnte kein Ubuntu-Rootfs herunterladen."
            exit 1
        }
    }

    wsl.exe --import $DistroName $DistroData $RootfsPath --version 2
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "wsl --import fehlgeschlagen. Stelle sicher, dass der Benutzer Schreibrechte auf $InstallRoot besitzt."
        exit 1
    }
    Write-Ok "Distro '$DistroName' importiert."
} else {
    Write-Ok "Distro '$DistroName' existiert bereits."
}

Write-Step "Pruefe Docker in der Test-Distro..."
$dockerCheck = wsl.exe -d $DistroName -u root -- bash -c "command -v docker >/dev/null 2>&1 && echo yes || echo no"
if ($dockerCheck.Trim() -ne "yes") {
    Write-Host "Installiere Docker Engine in der Test-Distro..." -ForegroundColor Yellow
    wsl.exe -d $DistroName -u root -- bash -c "export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y ca-certificates curl git && curl -fsSL https://get.docker.com | sh"
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Docker-Installation fehlgeschlagen."
        exit 1
    }
    Write-Ok "Docker Engine installiert."
} else {
    Write-Ok "Docker Engine bereits installiert."
}

Write-Step "Hole JOLIA-Code..."
$cloneCmd = "if [ -d $AppDirLinux/.git ]; then cd $AppDirLinux && git pull; else git clone $RepoUrl $AppDirLinux; fi"
wsl.exe -d $DistroName -u root -- bash -c $cloneCmd
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Git-Clone/Pull fehlgeschlagen."
    exit 1
}
Write-Ok "JOLIA-Code aktuell."

Write-Step "Starte Docker und JOLIA..."
$startCmd = "service docker start >/dev/null 2>&1 && cd $AppDirLinux && docker compose up -d --build"
wsl.exe -d $DistroName -u root -- bash -c $startCmd
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Docker oder JOLIA konnte nicht gestartet werden."
    Write-Warn "Manueller Start: wsl -d $DistroName -u root -- bash -c \"service docker start && cd $AppDirLinux && docker compose up -d\""
    exit 1
}

Write-Step "Pruefe JOLIA..."
$healthy = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$AppPort/health" -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    } catch { }
    Start-Sleep -Seconds 10
}

Write-Host ""
if ($healthy) {
    Write-Ok "JOLIA laeuft: http://localhost:$AppPort"
} else {
    Write-Warn "JOLIA antwortet noch nicht. Der Build oder Modell-Download kann im Hintergrund weiterlaufen."
}
Write-Host ""
Write-Host "=== Fertig ===" -ForegroundColor Cyan
Write-Host "Kein Windows-Autostart wurde angelegt." -ForegroundColor Green
Write-Host "Manueller Start: wsl -d $DistroName -u root -- bash -c \"service docker start && cd $AppDirLinux && docker compose up -d\"" -ForegroundColor DarkGray
Write-Host "Testinstallation: $InstallRoot" -ForegroundColor DarkGray
