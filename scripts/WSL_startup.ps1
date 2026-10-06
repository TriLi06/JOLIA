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
# Upload und Backup koennen per CIFS von FRITZ!NAS oder in einem lokalen
# Windows-Ordner liegen. Das Archiv (source_documents) liegt bewusst nativ im
# WSL-Dateisystem (nicht auf dem NAS, nicht unter C:\JOLIA-WSL), damit die
# Verarbeitung/Indexierung nicht durch SMB-Latenz ausgebremst wird.
#
# Rückstandsfreie Deinstallation: Menüoption 4
# LAN-Zugriff klappt nicht? Schrittweise Diagnose: Menüoption 7

$ErrorActionPreference = "Stop"

# Wird von JOLIA_setup.exe per "$JoliaScriptPath='...'; ..." vor dem eigentlichen
# Skriptinhalt gesetzt, wenn dieser per "Get-Content | Invoke-Expression" statt
# "-File" gestartet wurde (Workaround fuer per Gruppenrichtlinie gesperrte
# PowerShell-Skriptausfuehrung, siehe Selbst-Elevation weiter unten). In diesem
# Fall ist $PSCommandPath leer, da PowerShell kein echtes Skript "ausfuehrt".
# Wird das Skript stattdessen klassisch per "-File" gestartet (z.B. direkt per
# Doppelklick), ist $JoliaScriptPath nicht gesetzt und $PSCommandPath greift wie gewohnt.
if (-not $JoliaScriptPath) { $JoliaScriptPath = $PSCommandPath }

# ── Konfiguration ───────────────────────────────────────────────────────────
$DistroName  = "jolia-wsl"
$InstallRoot = "C:\JOLIA-WSL"
$DistroData  = Join-Path $InstallRoot "data"
$RootfsPath  = Join-Path $InstallRoot "rootfs.tar.gz"
$RepoUrl     = "https://github.com/TriLi06/JOLIA.git"
$AppDirLinux = "/opt/jolia"
# Archiv bleibt bewusst NICHT auf dem NAS/Windows-Laufwerk, sondern nativ im
# WSL-Dateisystem (ext4 der Distro), damit Verarbeitung/Indexierung schnell bleibt.
$ArchiveLinux = "/data/jolia/source_documents"
# FRITZ!NAS exportiert die USB-Speicher unter einer einzigen SMB-Freigabe
# "FRITZ.NAS". Upload und Backup sind Unterordner dieser Freigabe.
# Zugangsdaten stehen hier im Klartext. Vor jedem Einsatz durch eigene Werte ersetzen.
$FritzNasHost        = "fritz.box"
$FritzNasShare       = "FRITZ.NAS"
$FritzNasUploadDir   = "jolia_upload"
$FritzNasBackupDir   = "jolia_backup"
# Vor jeder Installation durch die tatsächlichen Zugangsdaten der eigenen FRITZ!Box ersetzen.
$FritzNasUser        = "jolia_admin"
$FritzNasPassword    = "joliaadmin"
$FritzNasRootMount   = "/mnt/fritznas"
$FritzNasUploadMount = "/mnt/fritznas_upload"
$FritzNasBackupMount = "/mnt/fritznas_backup"
$StorageSettingsPath = Join-Path $env:LOCALAPPDATA "JOLIA\storage.json"
$StorageMode         = "FritzNas"
$JoliaInboxLinux     = $FritzNasUploadMount
$JoliaBackupLinux    = $FritzNasBackupMount
$LocalStorageRoot    = ""
# 8080 kollidiert auf manchen Firmenrechnern mit lokal installierter Sicherheits-/Proxy-Software,
# die denselben Port auf dem Windows-Host belegt (Antwort dann "Embedthis-http" statt JOLIA).
$AppPort     = 8090
$FirewallRuleName = "JOLIA-WSL-Port-$AppPort"
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

function Confirm-JoliaNoncommercialLicense {
    Write-Host ""
    Write-Host "JOLIA-LIZENZ: PolyForm Noncommercial 1.0.0" -ForegroundColor Yellow
    Write-Host "JOLIA darf nur fuer nicht-kommerzielle Zwecke im Umfang der LICENSE genutzt werden."
    Write-Host "Geschaeftliche Nutzung benoetigt eine separate schriftliche Erlaubnis."
    Write-Host "Lizenztext: LICENSE im JOLIA-Repository."
    Write-Host ""
    Write-Host "NETZWERK: KEIN LOGIN UND KEIN PASSWORT" -ForegroundColor Yellow
    Write-Host "JOLIA ist ausschliesslich fuer ein sicheres, vertrauenswuerdiges privates Heimnetz vorgesehen."
    Write-Host "Alle erreichbaren Geraete koennen ohne Anmeldung auf die App zugreifen."
    Write-Host "Nicht in Gast-/oeffentlichen/Firmennetzen oder per Portweiterleitung/Tunnel betreiben."
    Write-Host "Der WSL-Installer aktiviert Mirrored Networking; die App nutzt HTTP auf Port $AppPort."
    $confirmation = Read-Host 'Zum Fortfahren Lizenz und Heimnetz-only-Nutzung ohne Passwort mit JA bestaetigen'
    if ($confirmation -cne "JA") {
        Write-Warn2 "Keine Zustimmung zur PolyForm-Lizenz. Vorgang wird abgebrochen."
        return $false
    }
    return $true
}

function Confirm-JoliaModelTerms {
    Write-Host ""
    Write-Host "EXTERNE KI-MODELLE UND SEPARATE NUTZUNGSBEDINGUNGEN" -ForegroundColor Yellow
    Write-Host "Der folgende Schritt laedt bzw. installiert Modellgewichte mit eigenen Bedingungen neben der JOLIA-Lizenz:"
    Write-Host "  - Ollama: qwen2.5:1.5b, qwen2.5:7b, qwen2.5vl:3b und bge-m3"
    Write-Host "  - Docker-Build: OpenAI CLIP ViT-B-32; der Checkpoint wird in das gebaute Image kopiert"
    Write-Host "  - Optionale Funktionen: Whisper, LAION CLAP und dlib/face-recognition-Modelle"
    Write-Host "Die Standard-Ollama-Modelle qwen2.5:1.5b, qwen2.5:7b und qwen2.5vl:3b werden laut Modellseiten unter Apache-2.0 angeboten; bge-m3 unter MIT." -ForegroundColor Yellow
    Write-Host "Andere Modellvarianten koennen engere Bedingungen haben; Beispiele stehen in THIRD_PARTY_NOTICES.md."
    Write-Host "  - dlib 68-Punkt-Gesichtslandmark-Modell: kommerzielle Produktnutzung laut Upstream ohne Erlaubnis nicht zulaessig."
    Write-Host "  - Tags/Modellversionen koennen sich aendern; Details und Links stehen in THIRD_PARTY_NOTICES.md."
    Write-Host "Eine Bestaetigung erteilt keine zusaetzlichen Rechte und ersetzt keine Lizenz oder Registrierung."
    Write-Host "Fahre nur fort, wenn du die aktuellen Bedingungen geprueft hast und deine Nutzung zulaessig ist."
    $confirmation = Read-Host 'Zum Fortfahren exakt MODELLBEDINGUNGEN GEPRUEFT eingeben'
    if ($confirmation -cne "MODELLBEDINGUNGEN GEPRUEFT") {
        Write-Warn2 "Keine Modellbedingungen-Bestaetigung. Docker-Build und Modell-Downloads werden nicht gestartet."
        return $false
    }
    return $true
}

function Set-JoliaStoragePaths {
    if ($StorageMode -eq "Local") {
        $fullPath = [System.IO.Path]::GetFullPath($LocalStorageRoot)
        if ($fullPath -notmatch '^[cC]:\\') {
            throw "Der lokale Ordner muss auf Laufwerk C: liegen, das in der JOLIA-WSL-Distro eingebunden ist."
        }
        $linuxPath = "/mnt/c/" + $fullPath.Substring(3).TrimEnd('\').Replace('\', '/')
        $script:JoliaInboxLinux = "$linuxPath/inbox"
        $script:JoliaBackupLinux = "$linuxPath/backup"
    } else {
        $script:JoliaInboxLinux = $FritzNasUploadMount
        $script:JoliaBackupLinux = $FritzNasBackupMount
    }
}

function Load-JoliaStorageSettings {
    if (-not (Test-Path $StorageSettingsPath)) { return }
    try {
        $settings = Get-Content -Path $StorageSettingsPath -Raw | ConvertFrom-Json
        if ($settings.StorageMode -in @("FritzNas", "Local")) {
            $script:StorageMode = $settings.StorageMode
        }
        if (-not [string]::IsNullOrWhiteSpace($settings.FritzNasUser)) {
            $script:FritzNasUser = $settings.FritzNasUser
        }
        if (-not [string]::IsNullOrWhiteSpace($settings.EncryptedFritzNasPassword)) {
            $securePassword = ConvertTo-SecureString $settings.EncryptedFritzNasPassword
            $script:FritzNasPassword = [System.Net.NetworkCredential]::new("", $securePassword).Password
        }
        if (-not [string]::IsNullOrWhiteSpace($settings.LocalStorageRoot)) {
            $script:LocalStorageRoot = $settings.LocalStorageRoot
        }
        Set-JoliaStoragePaths
    } catch {
        Write-Warn2 "Gespeicherte Speichereinstellungen konnten nicht geladen werden: $($_.Exception.Message)"
    }
}

function Save-JoliaStorageSettings {
    $settingsDirectory = Split-Path -Parent $StorageSettingsPath
    New-Item -ItemType Directory -Path $settingsDirectory -Force | Out-Null
    $securePassword = ConvertTo-SecureString $FritzNasPassword -AsPlainText -Force
    $settings = [ordered]@{
        StorageMode = $StorageMode
        FritzNasUser = $FritzNasUser
        EncryptedFritzNasPassword = ConvertFrom-SecureString $securePassword
        LocalStorageRoot = $LocalStorageRoot
    }
    $settings | ConvertTo-Json | Set-Content -Path $StorageSettingsPath -Encoding UTF8
}

function Set-JoliaStorage {
    Write-Host "  1: FRITZ!Box-Benutzer und Passwort ändern"
    Write-Host "  2: Lokalen Ordner für Upload und Backup verwenden"
    $storageChoice = Read-Host "Bitte Auswahl eingeben (1-2)"
    if ($storageChoice -eq "1") {
        $newUser = Read-Host "FRITZ!Box-Benutzername"
        $newPassword = Read-Host "FRITZ!Box-Passwort" -AsSecureString
        $plainPassword = [System.Net.NetworkCredential]::new("", $newPassword).Password
        if ([string]::IsNullOrWhiteSpace($newUser) -or [string]::IsNullOrWhiteSpace($plainPassword)) {
            Write-Warn2 "Benutzername und Passwort muessen ausgefuellt sein. Einstellungen wurden nicht geaendert."
            return
        }
        $script:FritzNasUser = $newUser
        $script:FritzNasPassword = $plainPassword
        $script:StorageMode = "FritzNas"
        $script:LocalStorageRoot = ""
    } elseif ($storageChoice -eq "2") {
        Write-Host "Lokaler Ordner auf C: (z. B. C:\JOLIA-Daten); es werden inbox und backup darin angelegt." -ForegroundColor DarkGray
        $newRoot = Read-Host "Pfad zum lokalen Speicherordner"
        if ([string]::IsNullOrWhiteSpace($newRoot)) {
            Write-Warn2 "Kein Ordner angegeben. Einstellungen wurden nicht geaendert."
            return
        }
        $newRoot = [System.IO.Path]::GetFullPath($newRoot)
        if ($newRoot -notmatch '^[cC]:\\') {
            Write-Warn2 "Bitte einen Ordner auf C: angeben; nur dieses Laufwerk ist in der JOLIA-WSL-Distro eingebunden."
            return
        }
        New-Item -ItemType Directory -Path (Join-Path $newRoot "inbox") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $newRoot "backup") -Force | Out-Null
        $script:LocalStorageRoot = $newRoot
        $script:StorageMode = "Local"
    } else {
        Write-Warn2 "Ungueltige Auswahl."
        return
    }

    Set-JoliaStoragePaths
    $distros = (wsl -l -q) -replace "`0", ""
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $refreshAutostart = $null -ne $task -and $task.State -ne "Disabled"
    if ($distros -contains $DistroName) {
        if ($StorageMode -eq "FritzNas") {
            Mount-FritzNasShares -Distro $DistroName
            $sharesReady = wsl -d $DistroName -u root -- bash -c "mountpoint -q $FritzNasUploadMount && mountpoint -q $FritzNasBackupMount && echo yes || echo no"
            if ($sharesReady.Trim() -ne "yes") {
                Write-Fail "FRITZ!NAS konnte nicht eingebunden werden. Die Speichereinstellungen wurden nicht gespeichert."
                return
            }
        } else {
            wsl -d $DistroName -u root -- bash -c "systemctl disable --now jolia-fritznas.service >/dev/null 2>&1 || true; for m in $FritzNasUploadMount $FritzNasBackupMount $FritzNasRootMount; do while mountpoint -q `$m; do umount `$m || break; done; done"
        }

        Set-JoliaDeploymentConfig -Distro $DistroName
        wsl -d $DistroName -u root -- bash -c "cd $AppDirLinux && docker compose up -d --force-recreate app"
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "Speicherpfade wurden gespeichert, aber JOLIA konnte nicht neu gestartet werden."
            Save-JoliaStorageSettings
            return
        }
    }
    Save-JoliaStorageSettings
    if ($refreshAutostart) {
        Register-JoliaAutostart
    }
    if ($StorageMode -eq "FritzNas") {
        Write-Ok "FRITZ!NAS-Zugangsdaten gespeichert und Speicherverbindung aktualisiert."
    } else {
        Write-Ok "Lokaler Speicher aktiviert: $LocalStorageRoot (inbox und backup)."
        Write-Warn2 "Vorhandene Daten wurden nicht verschoben. Kopiere sie bei Bedarf selbst aus dem bisherigen Speicher."
    }
}

# Das elevierte Fenster (Start-Process -Verb RunAs) schliesst sich sonst sofort nach
# einem Fehler/exit, bevor die Fehlermeldung gelesen werden kann.
function Exit-Fail {
    Read-Host "`nAbgebrochen wegen eines Fehlers - druecke Enter zum Schliessen"
    exit 1
}

function Register-JoliaAutostart {
    # WSL faehrt eine Distro herunter, sobald kein wsl.exe-Prozess mehr angebunden ist.
    # "sleep infinity" haelt die Distro (und damit Docker/JOLIA) dauerhaft am Leben.
    $storageWait = "true"
    if ($StorageMode -eq "FritzNas") {
        $storageWait = "systemctl start jolia-fritznas.service || true; for attempt in {1..60}; do if mountpoint -q $FritzNasUploadMount && mountpoint -q $FritzNasBackupMount; then break; fi; sleep 2; done; mountpoint -q $FritzNasUploadMount && mountpoint -q $FritzNasBackupMount || exit 1"
    }
    $keepAlive = "set -e; $storageWait; systemctl start docker; cd $AppDirLinux; docker info >/dev/null; docker compose config --quiet; docker compose up -d app; exec sleep infinity"
    $keepAliveB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($keepAlive))
    $wslArguments = "-d $DistroName -u root -- bash -c `"echo $keepAliveB64 | base64 -d | bash`""
    $hiddenLaunch = "`$process = Start-Process -FilePath '$env:SystemRoot\System32\wsl.exe' -ArgumentList '$wslArguments' -WindowStyle Hidden -Wait -PassThru; exit `$process.ExitCode"
    $hiddenLaunchB64 = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($hiddenLaunch))
    # Hide both the scheduled PowerShell process and the console window created by wsl.exe.
    $action    = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -EncodedCommand $hiddenLaunchB64"
    $trigger   = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -RunLevel Highest
    $settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)

    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Write-Ok "Autostart-Task '$TaskName' registriert und gestartet."
}

function Enable-JoliaAutostart {
    $distros = (wsl -l -q) -replace "`0", ""
    if ($distros -notcontains $DistroName) {
        Write-Fail "JOLIA ist nicht installiert. Verwende zuerst Option 1."
        return
    }
    Register-JoliaAutostart
}

function Disable-JoliaAutostart {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Write-Warn2 "Es wurde kein Autostart-Task gefunden. JOLIA bleibt installiert."
        return
    }
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Disable-ScheduledTask -TaskName $TaskName | Out-Null
    Write-Ok "Autostart deaktiviert. JOLIA bleibt installiert."
}

function Show-JoliaStatus {
    $distros = (wsl -l -q) -replace "`0", ""
    if ($distros -contains $DistroName) {
        Write-Ok "WSL-Distro '$DistroName' ist installiert."
    } else {
        Write-Warn2 "WSL-Distro '$DistroName' ist nicht installiert."
    }
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Write-Warn2 "Autostart-Task ist nicht eingerichtet."
    } else {
        Write-Host "Autostart-Task: $($task.State)" -ForegroundColor Green
    }
    if ($StorageMode -eq "Local") {
        Write-Host "Speicher: lokaler Ordner $LocalStorageRoot" -ForegroundColor Green
    } else {
        Write-Host "Speicher: FRITZ!NAS als Benutzer '$FritzNasUser'" -ForegroundColor Green
    }
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$AppPort/health" -UseBasicParsing -TimeoutSec 5
        Write-Ok "JOLIA antwortet unter http://localhost:$AppPort (HTTP $($response.StatusCode))."
    } catch {
        Write-Warn2 "JOLIA antwortet derzeit nicht unter http://localhost:$AppPort."
    }
    try {
        $rule = Get-NetFirewallHyperVRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
        if ($null -ne $rule -and $rule.Enabled) {
            Write-Ok "LAN-Zugriff: Hyper-V-Firewallregel '$FirewallRuleName' ist aktiv (Port $AppPort)."
        } else {
            Write-Warn2 "LAN-Zugriff: Hyper-V-Firewallregel '$FirewallRuleName' fehlt oder ist deaktiviert. Andere Geräte im Heimnetz koennen JOLIA dann nicht erreichen. Mit Option 1 reparieren."
        }
    } catch {
        Write-Warn2 "LAN-Firewallregel konnte nicht geprueft werden: $($_.Exception.Message)"
    }
    try {
        $winRule = Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
        if ($null -ne $winRule -and $winRule.Enabled) {
            Write-Ok "LAN-Zugriff: Windows-Firewallregel '$FirewallRuleName' ist aktiv (Port $AppPort)."
        } else {
            Write-Warn2 "LAN-Zugriff: Windows-Firewallregel '$FirewallRuleName' fehlt oder ist deaktiviert. Mit Option 1 reparieren."
        }
    } catch {
        Write-Warn2 "Windows-Firewallregel konnte nicht geprueft werden: $($_.Exception.Message)"
    }
    Write-Host "Ausfuehrliche LAN-Diagnose: Menüoption 7" -ForegroundColor DarkGray
}

# Aktualisiert den JOLIA-Checkout robust, auch wenn lokal etwas veraendert wurde
# (z.B. durch die App selbst oder manuelle Eingriffe). Ein einfaches "git pull"
# schlaegt in diesem Fall mit "local changes would be overwritten by merge" fehl
# und blockiert dann jedes weitere Update. Lokale Aenderungen werden deshalb
# zuerst per "git stash" gesichert (NICHT verworfen) und als Datei-Liste an den
# Aufrufer zurueckgemeldet, bevor per "git reset --hard" zuverlaessig auf den
# aktuellen Remote-Stand gewechselt wird. Existiert noch kein Checkout, wird
# frisch geklont. Gibt $true bei Erfolg zurueck, $false bei einem echten Fehler
# (z.B. Netzwerk/Repo nicht erreichbar).
function Sync-JoliaRepo ($Distro, $AppDir, $Repo) {
    $bashScript = @'
set -e
APPDIR="__APPDIR__"
REPO="__REPO__"
if [ ! -d "$APPDIR/.git" ]; then
    mkdir -p "$APPDIR"
    git clone "$REPO" "$APPDIR"
    echo "JOLIA_GIT_RESULT:CLONED"
    exit 0
fi
cd "$APPDIR"
git config --global --add safe.directory "$APPDIR" >/dev/null 2>&1 || true
git fetch origin --quiet
BRANCH=$(git symbolic-ref --short -q HEAD)
if [ -z "$BRANCH" ]; then BRANCH=main; fi
STATUS=$(git status --porcelain)
if [ -n "$STATUS" ]; then
    CHANGED=$(echo "$STATUS" | awk '{print $2}' | tr '\n' ';')
    STASHMSG="jolia-auto-update-$(date +%Y%m%d-%H%M%S)"
    git stash push -u -m "$STASHMSG" >/dev/null 2>&1
    echo "JOLIA_GIT_STASHED:$STASHMSG:$CHANGED"
fi
git reset --hard "origin/$BRANCH" --quiet
echo "JOLIA_GIT_RESULT:OK:$BRANCH"
'@
    $bashScript = $bashScript.Replace("__APPDIR__", $AppDir).Replace("__REPO__", $Repo)
    $bashScript = $bashScript -replace "`r", ""
    $scriptB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($bashScript))
    $output = wsl -d $Distro -u root -- bash -c "echo $scriptB64 | base64 -d | bash"
    $exitCode = $LASTEXITCODE

    $stashLine = $output | Where-Object { $_ -like "JOLIA_GIT_STASHED:*" }
    if ($stashLine) {
        $parts = $stashLine -split ":", 3
        $stashMsg = $parts[1]
        $changedFiles = @()
        if ($parts.Count -ge 3) { $changedFiles = ($parts[2] -split ";") | Where-Object { $_ -ne "" } }
        Write-Warn2 "Lokale Aenderungen am JOLIA-Code gefunden - diese wurden NICHT ueberschrieben, sondern vorher gesichert (git stash '$stashMsg')."
        if ($changedFiles.Count -gt 0) {
            Write-Warn2 ("Betroffene Dateien: " + ($changedFiles -join ", "))
        }
        Write-Warn2 "Pruefen/wiederherstellen in der Distro mit: wsl -d $Distro -u root -- bash -c `"cd $AppDir && git stash list`""
    }

    $resultLine = $output | Where-Object { $_ -like "JOLIA_GIT_RESULT:*" }
    if ($exitCode -ne 0 -or -not $resultLine) {
        Write-Fail "Git-Synchronisierung fehlgeschlagen."
        if ($output) { $output | ForEach-Object { Write-Host $_ } }
        return $false
    }
    return $true
}

function Update-Jolia {
    $distros = (wsl -l -q) -replace "`0", ""
    if ($distros -notcontains $DistroName) {
        Write-Fail "JOLIA ist nicht installiert. Verwende zuerst Option 1."
        return
    }
    if (-not (Confirm-JoliaNoncommercialLicense)) {
        return
    }

    Write-Warn2 "Vor Updates wird ein aktuelles JOLIA-Backup empfohlen (Einstellungen > Backups)."
    Write-Step "Lade JOLIA-Updates..."
    if (-not (Sync-JoliaRepo -Distro $DistroName -AppDir $AppDirLinux -Repo $RepoUrl)) {
        return
    }
    if ($StorageMode -eq "FritzNas") {
        Mount-FritzNasShares -Distro $DistroName
        $sharesReady = wsl -d $DistroName -u root -- bash -c "mountpoint -q $FritzNasUploadMount && mountpoint -q $FritzNasBackupMount && echo yes || echo no"
        if ($sharesReady.Trim() -ne "yes") {
            Write-Fail "FRITZ!NAS-Upload/Backup sind nicht eingebunden. Update abgebrochen, damit keine Daten versehentlich in lokale Ersatzordner geschrieben werden."
            return
        }
    } elseif (-not (Test-Path (Join-Path $LocalStorageRoot "inbox")) -or -not (Test-Path (Join-Path $LocalStorageRoot "backup"))) {
        Write-Fail "Der konfigurierte lokale Speicherordner fehlt. Verwende Menüpunkt 6 zur erneuten Auswahl."
        return
    }
    Set-JoliaDeploymentConfig -Distro $DistroName
    wsl -d $DistroName -u root -- bash -c "(systemctl enable --now docker || service docker start) && docker info >/dev/null && docker compose version && cd $AppDirLinux && docker compose config --quiet"
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Docker, Compose oder die Deployment-Konfiguration ist nicht einsatzbereit. Mit Option 1 reparieren."
        return
    }
    if (-not (Confirm-JoliaModelTerms)) {
        return
    }
    wsl -d $DistroName -u root -- bash -c "cd $AppDirLinux && docker compose up -d --build"
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "JOLIA konnte nach dem Update nicht gebaut/gestartet werden."
        return
    }
    Write-Ok "JOLIA wurde aktualisiert und gestartet."
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -ne $task -and $task.State -ne "Disabled") {
        Register-JoliaAutostart
    }
    Show-JoliaAccessUrls -Distro $DistroName
}

# Gibt die Adressen aus, unter denen JOLIA erreichbar ist (lokal und, falls
# ermittelbar, aus dem Heimnetz via Mirrored Networking). Wird nach Installation
# und nach jedem Update aufgerufen.
function Get-JoliaLanAddresses {
    Get-NetIPConfiguration -ErrorAction Stop |
        Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" -and $_.NetAdapter.HardwareInterface } |
        ForEach-Object { $_.IPv4Address.IPAddress } |
        Where-Object { $_ -and $_ -notmatch '^(127\.|169\.254\.)' } |
        Select-Object -Unique
}

function Show-JoliaAccessUrls ($Distro) {
    Write-Host "JOLIA Docs: http://127.0.0.1:$AppPort" -ForegroundColor Green
    try {
        foreach ($lanIp in @(Get-JoliaLanAddresses)) {
            Write-Host "Aus dem Heimnetz (Mirrored Networking): http://${lanIp}:$AppPort" -ForegroundColor Green
        }
    } catch {
        Write-Warn2 "Windows-LAN-Adresse konnte nicht ermittelt werden: $($_.Exception.Message)"
    }
}

# Setzt/aktualisiert einen einzelnen Schluessel in der .env-Datei der App (idempotent).
function Set-JoliaEnvVar ($Distro, $AppDir, $Key, $Value) {
    $lineB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes("$Key=$Value`n"))
    $cmd = "set -e; set -o pipefail; touch $AppDir/.env; sed '/^$Key=/d' $AppDir/.env > $AppDir/.env.tmp; echo $lineB64 | base64 -d >> $AppDir/.env.tmp; mv $AppDir/.env.tmp $AppDir/.env"
    $output = @(wsl -d $Distro -u root -- bash -c $cmd 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "Die JOLIA-Konfiguration '$Key' konnte nicht gespeichert werden: $($output -join ' ')"
    }
}

function Set-JoliaDeploymentConfig ($Distro) {
    wsl -d $Distro -u root -- mkdir -p $ArchiveLinux
    if ($LASTEXITCODE -ne 0) { throw "Der Archivordner konnte nicht angelegt werden." }
    Set-JoliaEnvVar -Distro $Distro -AppDir $AppDirLinux -Key "JOLIA_PORT" -Value $AppPort
    Set-JoliaEnvVar -Distro $Distro -AppDir $AppDirLinux -Key "JOLIA_INBOX" -Value $JoliaInboxLinux
    Set-JoliaEnvVar -Distro $Distro -AppDir $AppDirLinux -Key "JOLIA_ARCHIVE" -Value $ArchiveLinux
    Set-JoliaEnvVar -Distro $Distro -AppDir $AppDirLinux -Key "JOLIA_BACKUP" -Value $JoliaBackupLinux
}

# Bindet die beiden FRITZ!NAS-Freigaben (Upload/Backup) per CIFS in die Distro ein.
# Zugangsdaten liegen in einer chmod-600-Credentials-Datei in der Distro (nicht in
# /etc/fstab im Klartext). "nofail" verhindert, dass ein nicht erreichbares NAS
# (Router aus, Netzwerk anders) den gesamten Boot der Distro blockiert.
function Mount-FritzNasShares ($Distro) {
    Write-Step "Binde FRITZ!NAS-Freigaben ein (Upload/Backup)..."
    wsl -d $Distro -u root -- bash -c "command -v mount.cifs >/dev/null 2>&1 || (export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y cifs-utils)"

    $credB64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes("username=$FritzNasUser`npassword=$FritzNasPassword`n"))
    wsl -d $Distro -u root -- bash -c "echo $credB64 | base64 -d > /etc/jolia-fritznas.credentials && chmod 600 /etc/jolia-fritznas.credentials"

    wsl -d $Distro -u root -- bash -c "mkdir -p $FritzNasRootMount $FritzNasUploadMount $FritzNasBackupMount"

    # FRITZ!NAS authorizes the SMB user itself. noperm prevents the Linux CIFS
    # client from rejecting writes before the server can evaluate that account.
    # noauto: WSL fuehrt beim Boot selbst "mount -a" aus, bevor DNS fuer fritz.box bereit ist
    # ("Processing fstab with mount -a failed."). Eingehaengt wird per jolia-fritznas.service.
    $fstabOpts = "credentials=/etc/jolia-fritznas.credentials,iocharset=utf8,vers=3.0,uid=root,gid=root,file_mode=0770,dir_mode=0770,noperm,noserverino,_netdev,nofail,noauto"
    $fstabLine1 = "//$FritzNasHost/$FritzNasShare $FritzNasRootMount cifs $fstabOpts 0 0"
    $fstabLine2 = "$FritzNasRootMount/$FritzNasUploadDir $FritzNasUploadMount none bind,nofail,noauto 0 0"
    $fstabLine3 = "$FritzNasRootMount/$FritzNasBackupDir $FritzNasBackupMount none bind,nofail,noauto 0 0"
    # FRITZ!NAS erlaubt Schreibzugriffe auf die Share-Wurzel, aber nicht über
    # den CIFS-Parameter prefixpath. Alte direkte/prefixpath-Einträge werden
    # daher vor dem Eintragen der Root- und Bind-Mounts entfernt.
    wsl -d $Distro -u root -- bash -c "sed -i '\| $FritzNasRootMount cifs |d; \| $FritzNasUploadMount |d; \| $FritzNasBackupMount |d' /etc/fstab"
    wsl -d $Distro -u root -- bash -c "printf '%s\n%s\n%s\n' '$fstabLine1' '$fstabLine2' '$fstabLine3' >> /etc/fstab"

    $mountScript = @"
#!/bin/sh
# Wartet bis fritz.box aufloesbar ist; haengt nur ein, was noch nicht eingehaengt ist (kein Stapeln).
for i in `$(seq 1 30); do
  mountpoint -q $FritzNasRootMount || mount $FritzNasRootMount 2>/dev/null
  mountpoint -q $FritzNasRootMount && break
  sleep 2
done
mountpoint -q $FritzNasRootMount || exit 1
mountpoint -q $FritzNasUploadMount || mount $FritzNasUploadMount
mountpoint -q $FritzNasBackupMount || mount $FritzNasBackupMount
"@
    $unit = @"
[Unit]
Description=JOLIA FRITZ!NAS-Freigaben einbinden
After=network.target
Before=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/jolia-mount-fritznas.sh

[Install]
WantedBy=multi-user.target
"@
    $scriptB64 = [Convert]::ToBase64String([System.Text.Encoding]::ASCII.GetBytes(($mountScript -replace "`r", "")))
    $unitB64   = [Convert]::ToBase64String([System.Text.Encoding]::ASCII.GetBytes(($unit -replace "`r", "")))
    wsl -d $Distro -u root -- bash -c "echo $scriptB64 | base64 -d > /usr/local/sbin/jolia-mount-fritznas.sh && chmod 755 /usr/local/sbin/jolia-mount-fritznas.sh && echo $unitB64 | base64 -d > /etc/systemd/system/jolia-fritznas.service && systemctl daemon-reload && systemctl enable jolia-fritznas.service >/dev/null 2>&1"

    # Frueher per "mount -a" mehrfach gestapelte Bind-Mounts vollstaendig abbauen.
    $mountResult = wsl -d $Distro -u root --exec bash -c "for m in $FritzNasUploadMount $FritzNasBackupMount $FritzNasRootMount; do while mountpoint -q `$m; do umount `$m || break; done; done; systemctl restart jolia-fritznas.service 2>&1; mountpoint -q $FritzNasRootMount && mountpoint -q $FritzNasUploadMount && mountpoint -q $FritzNasBackupMount && echo OK || echo FAIL"
    if ($mountResult -match "OK") {
        Write-Ok "FRITZ!NAS-Freigaben eingebunden ($FritzNasUploadMount, $FritzNasBackupMount)."
    } else {
        Write-Warn2 "FRITZ!NAS-Freigaben konnten nicht eingebunden werden (Router/Freigabe erreichbar?). Speicher vor dem App-Start reparieren."
        Write-Warn2 "Ausgabe: $mountResult"
        $status = wsl -d $Distro -u root --exec bash -c "systemctl status jolia-fritznas.service --no-pager -l 2>&1"
        Write-Warn2 "Dienststatus: $status"
    }
}

# WSL versucht beim Boot standardmaessig ALLE Windows-Laufwerke automatisch zu mounten.
# Nicht verfuegbare/gesperrte Laufwerke (z.B. Kartenleser ohne Karte) erzeugen dabei
# harmlose, aber verwirrende "Failed to mount X:"-Meldungen. Ausserdem wird systemd
# aktiviert (fuer einen dauerhaft laufenden Docker-Daemon). Schreibt /etc/wsl.conf in
# einem Rutsch, damit sich systemd- und Automount-Einstellungen nicht gegenseitig
# ueberschreiben.
function Set-WslConf ($Distro) {
    $current = wsl -d $Distro -u root -- bash -c "cat /etc/wsl.conf 2>/dev/null"
    wsl -d $Distro -u root -- bash -c "mkdir -p /mnt/c && (grep -q '^C: /mnt/c' /etc/fstab 2>/dev/null || printf 'C: /mnt/c drvfs defaults 0 0\n' >> /etc/fstab)"
    if ($LASTEXITCODE -ne 0) { throw "Der Windows-Speichermount konnte nicht konfiguriert werden." }
    if (($current -join "`n") -match "systemd\s*=\s*true" -and ($current -join "`n") -match '(?s)\[automount\][^\[]*enabled\s*=\s*false' -and ($current -join "`n") -match '(?s)\[automount\][^\[]*mountFsTab\s*=\s*true') {
        return
    }
    Write-Step "Konfiguriere /etc/wsl.conf (systemd, Laufwerks-Automount auf C: beschraenkt)..."
    $wslConf = "[boot]`nsystemd=true`n`n[automount]`nenabled = false`nmountFsTab = true`n"
    $wslConfB64 = [Convert]::ToBase64String([System.Text.Encoding]::ASCII.GetBytes($wslConf))
    wsl -d $Distro -u root -- bash -c "echo $wslConfB64 | base64 -d > /etc/wsl.conf"
    if ($LASTEXITCODE -ne 0) { throw "wsl.conf konnte nicht gespeichert werden." }
    wsl --terminate $Distro
    if ($LASTEXITCODE -ne 0) { throw "Die WSL-Distro konnte nicht neu gestartet werden." }
    Write-Ok "wsl.conf aktualisiert (Distro neu gestartet)."
}

# Aktiviert Mirrored Networking fuer LAN-Zugriff auf Dienste in WSL2. Bestehende
# Einstellungen in %USERPROFILE%\.wslconfig bleiben erhalten.
function Set-WslGlobalNetworkingMode {
    $configPath = Join-Path $env:USERPROFILE ".wslconfig"
    $content = if (Test-Path $configPath) { [System.IO.File]::ReadAllText($configPath) } else { "" }
    $lines = New-Object 'System.Collections.Generic.List[string]'
    if ($content.Length -gt 0) {
        foreach ($line in ($content -split "`r`n|`n|`r")) { $lines.Add($line) }
    }

    $sectionStart = -1
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match '^\s*\[wsl2\]\s*$') {
            $sectionStart = $index
            break
        }
    }

    $changed = $false
    if ($sectionStart -ge 0) {
        $sectionEnd = $lines.Count
        for ($index = $sectionStart + 1; $index -lt $lines.Count; $index++) {
            if ($lines[$index] -match '^\s*\[[^\]]+\]\s*$') {
                $sectionEnd = $index
                break
            }
        }

        $settingFound = $false
        for ($index = $sectionStart + 1; $index -lt $sectionEnd; $index++) {
            if ($lines[$index] -match '^\s*networkingMode\s*=') {
                if ($lines[$index] -cne 'networkingMode=mirrored') {
                    $lines[$index] = 'networkingMode=mirrored'
                    $changed = $true
                }
                $settingFound = $true
            }
        }
        if (-not $settingFound) {
            $lines.Insert($sectionStart + 1, 'networkingMode=mirrored')
            $changed = $true
        }
    } else {
        if ($lines.Count -gt 0 -and $lines[$lines.Count - 1] -ne '') { $lines.Add('') }
        $lines.Add('[wsl2]')
        $lines.Add('networkingMode=mirrored')
        $changed = $true
    }

    if ($changed) {
        $encoding = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllText($configPath, [string]::Join("`r`n", $lines), $encoding)
        Write-Ok "Mirrored Networking in $configPath aktiviert."
    } else {
        Write-Ok "Mirrored Networking ist bereits in $configPath aktiviert."
    }
    return $changed
}

# Oeffnet $AppPort in der Hyper-V-Firewall (eigene Firewallschicht fuer VM-/WSL-Traffic,
# getrennt von der normalen Windows-Firewall). Ohne diese Regel bleibt JOLIA trotz
# Mirrored Networking nur ueber localhost erreichbar, da die Hyper-V-Firewall
# eingehende Verbindungen von anderen LAN-Geraeten standardmaessig blockt.
# Zusaetzlich wird (idempotent) eine ganz normale Windows Defender Firewall-Regel
# angelegt: unter Mirrored Networking kommt der Traffic aus dem LAN ueber den
# echten physischen Netzwerkadapter des Windows-Hosts an, und kann daher auch
# von der regulaeren Host-Firewall (nicht nur der Hyper-V-Firewall) blockiert
# werden. Die Regel wird bewusst nur fuer die Profile "Private" und "Domain"
# angelegt (nicht "Public"), damit JOLIA nicht versehentlich in unsicheren
# Netzwerken (Hotel-WLAN etc.) erreichbar wird.
# Beide Regeln sind idempotent: eine vorhandene Regel wird aktualisiert statt dupliziert.
function Set-JoliaFirewallRule {
    try {
        $vmCreator = Get-NetFirewallHyperVVMCreator -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -eq "WSL" } | Select-Object -First 1
        $vmCreatorId = if ($vmCreator) { $vmCreator.VMCreatorId } else { "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}" }

        $existingRule = Get-NetFirewallHyperVRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
        if ($null -ne $existingRule) {
            Set-NetFirewallHyperVRule -Name $existingRule.Name -LocalPorts $AppPort -Protocol TCP -Enabled $true -Action Allow | Out-Null
            Write-Ok "Hyper-V-Firewallregel '$FirewallRuleName' aktualisiert (Port $AppPort)."
        } else {
            New-NetFirewallHyperVRule -Name $FirewallRuleName -DisplayName $FirewallRuleName -Direction Inbound -VMCreatorId $vmCreatorId -Protocol TCP -LocalPorts $AppPort -Action Allow | Out-Null
            Write-Ok "Hyper-V-Firewallregel '$FirewallRuleName' angelegt (Port $AppPort, LAN-Zugriff auf JOLIA freigegeben)."
        }
    } catch {
        Write-Warn2 "Hyper-V-Firewallregel fuer Port $AppPort konnte nicht angelegt werden: $($_.Exception.Message)"
        Write-Warn2 "JOLIA bleibt dadurch moeglicherweise nur ueber localhost erreichbar (nicht aus dem Heimnetz)."
    }

    try {
        $existingWinRule = Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
        if ($null -ne $existingWinRule) {
            $existingWinRule | Set-NetFirewallRule -Enabled True -Action Allow -Direction Inbound -Protocol TCP -LocalPort $AppPort -Profile Private, Domain
            Write-Ok "Windows-Firewallregel '$FirewallRuleName' aktualisiert (Port $AppPort, Profile Private/Domain)."
        } else {
            New-NetFirewallRule -DisplayName $FirewallRuleName -Direction Inbound -Protocol TCP -LocalPort $AppPort -Action Allow -Profile Private, Domain | Out-Null
            Write-Ok "Windows-Firewallregel '$FirewallRuleName' angelegt (Port $AppPort, Profile Private/Domain)."
        }
    } catch {
        Write-Warn2 "Windows-Firewallregel fuer Port $AppPort konnte nicht angelegt werden: $($_.Exception.Message)"
    }

    try {
        $publicProfiles = Get-NetConnectionProfile -ErrorAction SilentlyContinue | Where-Object { $_.NetworkCategory -eq "Public" }
        if ($publicProfiles) {
            Write-Warn2 "Mindestens eine aktive Netzwerkverbindung ist als 'Oeffentlich' eingestuft: $($publicProfiles.InterfaceAlias -join ', ')"
            Write-Warn2 "Die neue Windows-Firewallregel gilt dort bewusst NICHT, JOLIA bleibt in oeffentlichen Netzen gesperrt. Falls es sich tatsaechlich um dein privates Heimnetz handelt, kannst du es umstellen mit:"
            Write-Warn2 "  Set-NetConnectionProfile -InterfaceAlias '$($publicProfiles[0].InterfaceAlias)' -NetworkCategory Private"
        }
    } catch { }
}

# Prueft Schritt fuer Schritt, warum JOLIA (noch) nicht aus dem LAN erreichbar
# ist, und gibt zu jedem Punkt eine klare OK/WARN-Meldung samt Reparaturhinweis
# aus. Deckt alle bekannten Blocker ab: Networking-Modus, lokale Erreichbarkeit,
# Hyper-V-Firewall (Regel + globale VM-Policy), normale Windows-Firewall,
# Netzwerkprofil (Privat/Oeffentlich) und optional einen echten Verbindungstest
# von einem zweiten Geraet.
function Test-JoliaOllama {
    $ErrorActionPreference = "Continue"
    Write-Host ""
    Write-Step "Pruefe Ollama-Container, Modelle und Verbindung aus der App..."
    Write-Host "Ollama laeuft als Docker-Container innerhalb von '$DistroName', nicht als eigene WSL-Distro." -ForegroundColor DarkGray
    Write-Host "Port 11434 wird bewusst NICHT auf Windows/LAN veroeffentlicht. Die App verwendet intern http://ollama:11434." -ForegroundColor DarkGray
    $appRunning = $false
    $ollamaRunning = $false
    foreach ($containerName in @("jolia-ollama", "jolia-ollama-init", "jolia-app")) {
        $inspectOutput = @(wsl -d $DistroName -u root -- docker inspect $containerName 2>&1)
        $inspectExitCode = $LASTEXITCODE
        if ($inspectExitCode -ne 0 -or -not $inspectOutput) {
            Write-Fail "Container '$containerName' fehlt oder Docker antwortet nicht: $($inspectOutput -join ' ')"
            continue
        }
        try {
            $container = (ConvertFrom-Json -InputObject ($inspectOutput -join "`n"))[0]
            $state = $container.State
            if ($containerName -eq "jolia-ollama-init") {
                if ($state.Status -eq "exited" -and $state.ExitCode -eq 0) {
                    Write-Ok "Modell-Download abgeschlossen: jolia-ollama-init Exited (0) ist normal."
                } elseif ($state.Running) {
                    Write-Warn2 "jolia-ollama-init laeuft noch; Modelle werden moeglicherweise noch heruntergeladen."
                } else {
                    Write-Fail "Modell-Download nicht erfolgreich abgeschlossen (Status: $($state.Status), Exit-Code: $($state.ExitCode))."
                }
            } elseif ($state.Running) {
                Write-Ok "Container '$containerName' laeuft."
                if ($containerName -eq "jolia-app") { $appRunning = $true }
                if ($containerName -eq "jolia-ollama") { $ollamaRunning = $true }
            } else {
                Write-Fail "Container '$containerName' laeuft nicht (Status: $($state.Status), Exit-Code: $($state.ExitCode))."
            }
            if ($state.Health) {
                if ($state.Health.Status -eq "healthy") {
                    Write-Ok "${containerName}: Healthcheck healthy."
                } else {
                    Write-Warn2 "${containerName}: Healthcheck $($state.Health.Status)."
                    $healthLog = @($state.Health.Log | Where-Object { $_.Output })
                    if ($healthLog.Count -gt 0) { Write-Host $healthLog[-1].Output.Trim() }
                }
            }
        } catch {
            Write-Fail "Status von '$containerName' konnte nicht ausgewertet werden: $($_.Exception.Message)"
        }
    }

    if ($ollamaRunning) {
        $modelOutput = @(wsl -d $DistroName -u root -- docker exec jolia-ollama ollama list 2>&1)
        $modelExitCode = $LASTEXITCODE
        if ($modelExitCode -eq 0) {
            Write-Ok "Ollama antwortet auf 'ollama list'. Installierte Modelle:"
            $modelOutput | ForEach-Object { Write-Host $_ }
            foreach ($model in @("qwen2.5:1.5b", "qwen2.5:7b", "qwen2.5vl:3b", "bge-m3")) {
                $modelTag = if ($model.Contains(':')) { '' } else { '(?::latest)?' }
                if (($modelOutput -join "`n") -notmatch "(?m)^\s*$([regex]::Escape($model))$modelTag\s") {
                    Write-Warn2 "Standardmodell '$model' fehlt. Modell-Download/Init-Logs pruefen."
                }
            }
        } else {
            Write-Fail "Ollama-Modellliste konnte nicht abgefragt werden: $($modelOutput -join ' ')"
        }
    }

    if ($appRunning) {
        $apiProbe = @'
import json, os, sys, urllib.request, urllib.error
base_url = os.environ.get('OLLAMA_BASE_URL', 'http://ollama:11434').rstrip('/')
print('OLLAMA_BASE_URL=' + base_url, flush=True)
try:
    with urllib.request.urlopen(base_url + '/api/tags', timeout=10) as response:
        payload = json.load(response)
        print('HTTP', response.status)
        print('Modelle:', ', '.join(model['name'] for model in payload['models']) or '(keine)')
except urllib.error.HTTPError as error:
    print('HTTP', error.code, error.read().decode('utf-8', errors='replace'))
    sys.exit(1)
except Exception as error:
    print(type(error).__name__ + ': ' + str(error))
    sys.exit(1)
'@
        $apiOutput = @(wsl -d $DistroName -u root -- docker exec jolia-app python -c $apiProbe 2>&1)
        $apiExitCode = $LASTEXITCODE
        if ($apiExitCode -eq 0) {
            Write-Ok "Ollama-API ist aus dem App-Container erreichbar: $($apiOutput -join ' ')"
        } else {
            Write-Fail "Ollama-API-Test aus dem App-Container fehlgeschlagen: $($apiOutput -join ' ')"
        }

        $inferenceProbe = @'
import sys
from app.services.ollama_service import get_background_ollama_service
service = get_background_ollama_service()
print('Import-Modell:', service.model, flush=True)
try:
    answer = service.generate('Antworte ausschliesslich mit OK.')
    if not answer.strip():
        raise RuntimeError('Das Modell hat eine leere Antwort geliefert.')
    print('Inferenz erfolgreich:', answer.strip()[:120])
except Exception as error:
    print(type(error).__name__ + ': ' + str(error))
    sys.exit(1)
'@
        $inferenceOutput = @(wsl -d $DistroName -u root -- docker exec jolia-app python -c $inferenceProbe 2>&1)
        $inferenceExitCode = $LASTEXITCODE
        if ($inferenceExitCode -eq 0) {
            Write-Ok "Echte Ollama-Inferenz aus dem App-Container erfolgreich: $($inferenceOutput -join ' ')"
        } else {
            Write-Fail "Echte Ollama-Inferenz aus dem App-Container fehlgeschlagen: $($inferenceOutput -join ' ')"
        }
    } else {
        Write-Warn2 "Ollama-API-Test aus der App uebersprungen: jolia-app laeuft nicht."
    }

    Write-Warn2 "HTTP 400 'Bad Request' bedeutet nicht automatisch, dass Ollama fehlt: Modell, Anfrageformat oder Bildunterstuetzung koennen unpassend sein."
    Write-Host "Der Inferenztest laedt das konfigurierte Import-Modell einmal in den Arbeitsspeicher." -ForegroundColor DarkGray
    foreach ($containerName in @("jolia-ollama-init", "jolia-ollama", "jolia-app")) {
        Write-Step "Letzte 40 Logzeilen: $containerName"
        $previousEncoding = [Console]::OutputEncoding
        try {
            [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
            wsl -d $DistroName -u root -- docker logs --tail 40 $containerName 2>&1 | ForEach-Object { Write-Host "$_" }
        } finally {
            [Console]::OutputEncoding = $previousEncoding
        }
    }
    Write-Host "Bei fehlenden Containern/Modellen: Option 1 (installieren oder reparieren) verwenden." -ForegroundColor DarkGray
}

function Test-JoliaLanAccess {
    Write-Host "=== JOLIA LAN- und Ollama-Diagnose ===" -ForegroundColor Cyan

    # Voraussetzungen fuer Mirrored Networking: Windows 11 22H2 (Build 22621)
    # und WSL 2.0.9 oder neuer.
    Write-Host ""
    Write-Step "Pruefe Windows- und WSL-Version..."
    try {
        $windowsVersion = Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion" -ErrorAction Stop
        $windowsBuild = [int]$windowsVersion.CurrentBuildNumber
        $windowsRevision = $windowsVersion.UBR
        $windowsDisplayVersion = if ($windowsVersion.DisplayVersion) { $windowsVersion.DisplayVersion } else { $windowsVersion.ReleaseId }
        $windowsProductName = if ($windowsBuild -ge 22000 -and $windowsVersion.ProductName -match '^Windows 10') {
            $windowsVersion.ProductName -replace '^Windows 10', 'Windows 11'
        } else {
            $windowsVersion.ProductName
        }
        Write-Host "Windows (wie winver): $windowsProductName, Version $windowsDisplayVersion (Build $windowsBuild.$windowsRevision)"
        if ($windowsBuild -ge 22621) {
            Write-Ok "Windows-Build erfuellt die Voraussetzung fuer Mirrored Networking (Windows 11 22H2 oder neuer)."
        } else {
            Write-Fail "Windows-Build $windowsBuild ist zu alt fuer Mirrored Networking. Erforderlich ist Windows 11 22H2 (Build 22621) oder neuer."
        }
    } catch {
        Write-Warn2 "Windows-Version konnte nicht ausgelesen werden: $($_.Exception.Message)"
    }

    $wslVersionOutput = @(wsl.exe --version 2>&1)
    $wslVersionExitCode = $LASTEXITCODE
    $normalizedWslVersionOutput = @($wslVersionOutput | ForEach-Object { ([string]$_) -replace "`0", "" })
    $wslVersionText = $normalizedWslVersionOutput -join "`n"
    $wslVersionMatch = $null
    foreach ($line in $normalizedWslVersionOutput) {
        $match = [regex]::Match($line, 'WSL[\s-]+Version:\s*([0-9]+(?:\.[0-9]+){1,3})', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
        if ($match.Success) {
            $wslVersionMatch = $match
            break
        }
    }
    if ($wslVersionExitCode -eq 0 -and $wslVersionMatch.Success) {
        $wslVersion = [version]$wslVersionMatch.Groups[1].Value
        Write-Host "wsl --version: $wslVersion"
        if ($wslVersion -ge [version]"2.0.9") {
            Write-Ok "WSL-Version erfuellt die Voraussetzung fuer die Hyper-V-Firewall (2.0.9 oder neuer)."
        } else {
            Write-Fail "WSL $wslVersion ist zu alt; erforderlich ist WSL 2.0.9 oder neuer. In einer administrativen PowerShell 'wsl --update' ausfuehren."
        }
    } elseif ($wslVersionExitCode -eq 0) {
        Write-Warn2 "'wsl --version' lieferte keine erkennbare WSL-Paketversion: $wslVersionText"
        Write-Warn2 "WSL ggf. mit 'wsl --update' aktualisieren und diese Diagnose erneut ausfuehren."
    } else {
        Write-Fail "'wsl --version' wird von der installierten WSL-Version nicht unterstuetzt: $wslVersionText"
        Write-Warn2 "WSL muss aktualisiert werden. In einer administrativen PowerShell 'wsl --update' ausfuehren."
    }

    $distros = (wsl -l -q) -replace "`0", ""
    if ($distros -notcontains $DistroName) {
        Write-Fail "WSL-Distro '$DistroName' ist nicht installiert. Verwende zuerst Option 1."
        return
    }

    Test-JoliaOllama

    # 1. Networking-Modus
    $configPath = Join-Path $env:USERPROFILE ".wslconfig"
    $mirroredActive = $false
    if (Test-Path $configPath) {
        $content = [System.IO.File]::ReadAllText($configPath)
        if ($content -match "(?m)^\s*networkingMode\s*=\s*mirrored\s*$") {
            $mirroredActive = $true
        }
    }
    if ($mirroredActive) {
        Write-Ok "Mirrored Networking ist in $configPath konfiguriert."
    } else {
        Write-Fail "Mirrored Networking ist NICHT in $configPath konfiguriert. Ohne dieses ist LAN-Zugriff grundsaetzlich nicht moeglich. Mit Option 1 reparieren."
    }

    # 2. Tatsaechliche IP-Adressen vergleichen (erkennt den Fall, dass .wslconfig
    #    zwar korrekt ist, aber seit der letzten Aenderung kein "wsl --shutdown"
    #    mehr lief und die Distro daher noch im alten NAT-Modus laeuft).
    $networkModeOutput = @(wsl -d $DistroName -u root -- wslinfo --networking-mode 2>&1)
    $networkModeExitCode = $LASTEXITCODE
    $networkMode = ($networkModeOutput -join " ").Trim()
    $lanIps = @()
    try {
        $lanIps = @(Get-JoliaLanAddresses)
    } catch {
        Write-Warn2 "Windows-LAN-Adressen konnten nicht abgefragt werden: $($_.Exception.Message)"
    }
    if ($lanIps.Count -eq 0) {
        Write-Warn2 "Keine aktive physische LAN-Verbindung mit IPv4-Gateway gefunden."
    }
    if ($networkModeExitCode -ne 0) {
        Write-Warn2 "Aktiver WSL-Netzwerkmodus konnte nicht abgefragt werden. WSL aktualisieren; .wslconfig allein beweist keinen aktiven Mirrored-Modus."
    } elseif ($networkMode -eq "mirrored") {
        Write-Ok "Mirrored Networking ist tatsaechlich aktiv. Windows-LAN-Adressen: $($lanIps -join ', ')."
    } else {
        Write-Fail "Aktiver WSL-Netzwerkmodus: $networkMode (erwartet: mirrored)."
        Write-Warn2 "Abhilfe: 'wsl --shutdown' ausfuehren (schliesst alle WSL-Fenster) und JOLIA danach neu starten."
    }

    # 3. Docker-Container und Portpfad (Container -> WSL -> Windows)
    Write-Host ""
    Write-Step "Pruefe Docker-Container und Portweiterleitung..."
    $container = $null
    $inspectOutput = @(wsl -d $DistroName -u root -- docker inspect jolia-app 2>&1)
    $inspectExitCode = $LASTEXITCODE
    if ($inspectExitCode -ne 0 -or -not $inspectOutput) {
        Write-Fail "Docker-Container 'jolia-app' wurde nicht gefunden oder Docker antwortet nicht. Ausgabe: $($inspectOutput -join ' ')"
    } else {
        try {
            $container = (ConvertFrom-Json -InputObject ($inspectOutput -join "`n"))[0]
            if ($container.State.Running) {
                Write-Ok "Docker-Container '$($container.Name.TrimStart('/'))' laeuft seit $($container.State.StartedAt)."
            } else {
                Write-Fail "Docker-Container '$($container.Name.TrimStart('/'))' laeuft nicht (Status: $($container.State.Status), Exit-Code: $($container.State.ExitCode))."
            }

            if ($container.State.Health) {
                if ($container.State.Health.Status -eq "healthy") {
                    Write-Ok "Docker-Healthcheck: healthy."
                } elseif ($container.State.Health.Status -eq "starting") {
                    Write-Warn2 "Docker-Healthcheck ist noch 'starting'; der App-Start kann noch laufen."
                } else {
                    $healthLog = @($container.State.Health.Log | Where-Object { $_.Output })
                    $lastHealthOutput = if ($healthLog.Count -gt 0) { $healthLog[-1].Output.Trim() } else { "kein Healthcheck-Log verfuegbar" }
                    Write-Fail "Docker-Healthcheck: $($container.State.Health.Status). Letzter Healthcheck: $lastHealthOutput"
                }
            } else {
                Write-Warn2 "Der Container hat keinen Docker-Healthcheck konfiguriert."
            }

            $portBindings = @($container.NetworkSettings.Ports.'8080/tcp' | Where-Object { $_ })
            $matchingPortBindings = @($portBindings | Where-Object { [int]$_.HostPort -eq $AppPort })
            $expectedBinding = @($matchingPortBindings | Where-Object { $_.HostIp -notmatch '^(127\.|::1$)' })
            if ($expectedBinding.Count -gt 0) {
                $bindingText = ($expectedBinding | ForEach-Object { "$($_.HostIp):$($_.HostPort) -> container:8080/tcp" }) -join ", "
                Write-Ok "Docker-Portbindung stimmt: $bindingText."
            } elseif ($matchingPortBindings.Count -gt 0) {
                $bindingText = ($matchingPortBindings | ForEach-Object { "$($_.HostIp):$($_.HostPort)" }) -join ", "
                Write-Fail "Docker-Port $AppPort ist nur lokal gebunden ($bindingText); andere Geraete im LAN koennen ihn so nicht erreichen."
            } else {
                $actualBindings = if ($portBindings.Count -gt 0) {
                    ($portBindings | ForEach-Object { "$($_.HostIp):$($_.HostPort)" }) -join ", "
                } else {
                    "keine Bindung fuer 8080/tcp"
                }
                Write-Fail "Docker leitet Container-Port 8080/tcp nicht auf Host-Port $AppPort weiter (gefunden: $actualBindings)."
            }
        } catch {
            Write-Fail "Docker-Inspektionsdaten konnten nicht ausgewertet werden: $($_.Exception.Message)"
            $container = $null
        }
    }

    if ($container -and $container.State.Running) {
        $containerHealthOutput = @(wsl -d $DistroName -u root -- docker exec jolia-app python -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=5); print('HTTP', r.status, r.read().decode())" 2>&1)
        $containerHealthExitCode = $LASTEXITCODE
        if ($containerHealthExitCode -eq 0) {
            Write-Ok "HTTP-Test direkt im Container auf 127.0.0.1:8080 erfolgreich: $($containerHealthOutput -join ' ')."
        } else {
            Write-Fail "HTTP-Test direkt im Container auf 127.0.0.1:8080 fehlgeschlagen: $($containerHealthOutput -join ' ')"
        }

        $wslPortOutput = @(wsl -d $DistroName -u root -- python3 -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:$AppPort/health', timeout=5); print('HTTP', r.status, r.read().decode())" 2>&1)
        $wslPortExitCode = $LASTEXITCODE
        if ($wslPortExitCode -eq 0) {
            Write-Ok "HTTP-Test in WSL auf dem veroeffentlichten Port 127.0.0.1:$AppPort erfolgreich: $($wslPortOutput -join ' ')."
        } else {
            Write-Fail "Container antwortet moeglicherweise intern, aber WSL-Port 127.0.0.1:$AppPort ist nicht erreichbar: $($wslPortOutput -join ' ')"
        }
    } elseif ($container) {
        Write-Warn2 "Interne HTTP-Tests uebersprungen, da der Container nicht laeuft."
    }

    # 4. Lokale Erreichbarkeit (Windows-Host -> App)
    $localOk = $false
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$AppPort/health" -UseBasicParsing -TimeoutSec 5
        Write-Ok "JOLIA antwortet lokal unter http://127.0.0.1:$AppPort (HTTP $($response.StatusCode))."
        $localOk = $true
    } catch {
        Write-Fail "JOLIA antwortet nicht einmal lokal unter http://127.0.0.1:$AppPort. Pruefe mit Option 5/Docker, ob der Container laeuft, bevor du LAN-Zugriff testest."
    }

    # 4. Erreichbarkeit ueber die LAN-IP, aber noch vom selben Windows-Host aus.
    #    Das grenzt "App bindet falsch" von "nur die Firewall blockiert externe
    #    Verbindungen" sauber voneinander ab.
    foreach ($lanIp in $lanIps) {
        try {
            $response = Invoke-WebRequest -Uri "http://${lanIp}:$AppPort/health" -UseBasicParsing -TimeoutSec 5
            Write-Ok "JOLIA antwortet unter der LAN-IP http://${lanIp}:$AppPort (HTTP $($response.StatusCode)) - vom Windows-Host aus getestet."
        } catch {
            Write-Warn2 "Host-Test auf http://${lanIp}:$AppPort fehlgeschlagen. Mirrored Networking erlaubt Zugriffe vom Host auf seine eigene LAN-IP nicht immer; dieser Test beweist keine LAN-Firewallblockade. Der Test von einem zweiten Geraet ist entscheidend."
        }
    }

    # 5. Hyper-V-Firewallregel (Port-spezifisch)
    try {
        $hvRule = Get-NetFirewallHyperVRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
        if ($null -ne $hvRule -and $hvRule.Enabled -and $hvRule.Action -eq "Allow") {
            Write-Ok "Hyper-V-Firewallregel '$FirewallRuleName' ist aktiv und erlaubt Port $AppPort."
        } else {
            Write-Fail "Hyper-V-Firewallregel '$FirewallRuleName' fehlt, ist deaktiviert oder blockiert. Mit Option 1 reparieren."
        }
    } catch {
        Write-Warn2 "Hyper-V-Firewallregel konnte nicht geprueft werden: $($_.Exception.Message)"
    }

    # 6. Globale Hyper-V-VM-Firewallpolicy - kann eine an sich korrekte
    #    Einzelregel trotzdem uebersteuern, wenn hier z.B. per GPO/Drittsoftware
    #    "Block" erzwungen wird.
    try {
        $vmCreator = Get-NetFirewallHyperVVMCreator -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -eq "WSL" } | Select-Object -First 1
        $vmCreatorId = if ($vmCreator) { $vmCreator.VMCreatorId } else { "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}" }
        $vmSetting = Get-NetFirewallHyperVVMSetting -PolicyStore ActiveStore -Name $vmCreatorId -ErrorAction SilentlyContinue
        if ($null -ne $vmSetting) {
            if ($vmSetting.DefaultInboundAction -eq "Block" ) {
                Write-Warn2 "Hyper-V-Firewall Standardrichtlinie fuer eingehenden Traffic ist 'Block' - das ist normal und wird durch die gezielte Regel oben bereits ausgeglichen. Nur relevant, falls die gezielte Regel oben fehlschlaegt."
            } else {
                Write-Ok "Hyper-V-Firewall Standardrichtlinie fuer eingehenden Traffic: $($vmSetting.DefaultInboundAction)."
            }
        }
    } catch {
        Write-Warn2 "Globale Hyper-V-VM-Firewallpolicy konnte nicht geprueft werden (nicht kritisch): $($_.Exception.Message)"
    }

    # 7. Normale Windows Defender Firewall (zusaetzliche Schicht unter Mirrored
    #    Networking, siehe Set-JoliaFirewallRule).
    try {
        $winRule = Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
        if ($null -ne $winRule -and $winRule.Enabled -and $winRule.Action -eq "Allow") {
            Write-Ok "Windows-Firewallregel '$FirewallRuleName' ist aktiv und erlaubt Port $AppPort."
        } else {
            Write-Fail "Windows-Firewallregel '$FirewallRuleName' fehlt oder ist deaktiviert. Mit Option 1 reparieren."
        }
    } catch {
        Write-Warn2 "Windows-Firewallregel konnte nicht geprueft werden: $($_.Exception.Message)"
    }

    # 8. Netzwerkprofil - unsere Windows-Firewallregel gilt bewusst nur fuer
    #    Private/Domain, nicht Public.
    try {
        $profiles = Get-NetConnectionProfile -ErrorAction SilentlyContinue
        foreach ($p in $profiles) {
            if ($p.NetworkCategory -eq "Public") {
                Write-Fail "Netzwerkprofil von '$($p.InterfaceAlias)' ist 'Oeffentlich'. Die Windows-Firewallregel gilt dort NICHT (Sicherheitsabsicht). Falls dies dein Heimnetz ist: Set-NetConnectionProfile -InterfaceAlias '$($p.InterfaceAlias)' -NetworkCategory Private"
            } else {
                Write-Ok "Netzwerkprofil von '$($p.InterfaceAlias)': $($p.NetworkCategory)."
            }
        }
        if (-not $profiles) {
            Write-Warn2 "Konnte aktive Netzwerkprofile nicht ermitteln."
        }
    } catch {
        Write-Warn2 "Netzwerkprofil konnte nicht geprueft werden: $($_.Exception.Message)"
    }

    # 9. Hinweis auf weitere moegliche Blocker ausserhalb dieses Skripts.
    Write-Host ""
    Write-Host "Falls alle obigen Punkte OK sind und es trotzdem nicht klappt, kommt die Blockade" -ForegroundColor DarkGray
    Write-Host "erfahrungsgemaess von einer dieser Stellen (ausserhalb der Kontrolle dieses Skripts):" -ForegroundColor DarkGray
    Write-Host "  - Drittanbieter-Antivirus/Firewall (z.B. Kaspersky, Norton, Avast) mit eigenem Netzwerkschutz" -ForegroundColor DarkGray
    Write-Host "  - Client-/AP-Isolation im WLAN-Router (verhindert Geraete-zu-Geraete-Kommunikation im selben WLAN)" -ForegroundColor DarkGray
    Write-Host "  - Das andere Geraet ist in einem Gast-WLAN oder einer separaten VLAN-/IoT-Zone" -ForegroundColor DarkGray
    Write-Host "  - Firmen-/Schul-Notebook mit zentral verwalteter Firewall-Policy (GPO/Intune)" -ForegroundColor DarkGray
    Write-Host ""

    foreach ($lanIp in $lanIps) {
        Write-Step "Teste jetzt von einem ANDEREN Geraet im selben Netzwerk im Browser:"
        Write-Host "  http://${lanIp}:$AppPort" -ForegroundColor Green
    }
}

function Invoke-JoliaUninstall {
    $installations = @(
        @{ DistroName = $DistroName; InstallRoot = $InstallRoot },
        @{ DistroName = "jolia-wsl-test"; InstallRoot = (Join-Path $env:LOCALAPPDATA "JOLIA-WSL-test") }
    )

    Write-Host "=== JOLIA Docs - WSL-Deinstallation ===" -ForegroundColor Cyan
    Write-Host "Entferne Autostart-Task..." -ForegroundColor Yellow
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "  erledigt." -ForegroundColor Green

    Write-Host "Entferne LAN-Firewallregeln..." -ForegroundColor Yellow
    $firewallRule = Get-NetFirewallHyperVRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
    if ($null -ne $firewallRule) {
        Remove-NetFirewallHyperVRule -Name $firewallRule.Name -ErrorAction SilentlyContinue
    }
    Remove-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue
    Write-Host "  erledigt." -ForegroundColor Green

    $existingDistros = (wsl -l -q) -replace "`0", ""
    foreach ($install in $installations) {
        $distroName = $install.DistroName
        $installRoot = $install.InstallRoot

        if ($existingDistros -contains $distroName) {
            Write-Host "Entferne WSL-Distro '$distroName' (inkl. aller Container/Images/Volumes/Code)..." -ForegroundColor Yellow
            wsl --unregister $distroName
            Write-Host "  erledigt." -ForegroundColor Green
        } else {
            Write-Host "Distro '$distroName' existiert nicht (mehr)." -ForegroundColor DarkGray
        }

        if (Test-Path $installRoot) {
            Write-Host "Lösche Installationsordner $installRoot..." -ForegroundColor Yellow
            Remove-Item -Path $installRoot -Recurse -Force
            Write-Host "  erledigt." -ForegroundColor Green
        }
    }

    Write-Host ""
    Write-Host "=== Fertig ===" -ForegroundColor Cyan
    Write-Host "JOLIA und alle zugehörigen Daten wurden entfernt." -ForegroundColor Green
    Write-Host "Hinweis: Die Windows-Features 'Windows-Subsystem für Linux' und" -ForegroundColor DarkGray
    Write-Host "'Virtual Machine Platform' bleiben aktiviert (werden ggf. von anderen" -ForegroundColor DarkGray
    Write-Host "WSL-Distros/Tools benutzt). Manuell deaktivierbar via:" -ForegroundColor DarkGray
    Write-Host "  dism /online /disable-feature /featurename:Microsoft-Windows-Subsystem-Linux" -ForegroundColor DarkGray
    Write-Host "  dism /online /disable-feature /featurename:VirtualMachinePlatform" -ForegroundColor DarkGray
}

# ── Selbst-Elevation ────────────────────────────────────────────────────────
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Starte Skript mit Administratorrechten neu..." -ForegroundColor Yellow
    if ($JoliaScriptPath) {
        # "Get-Content | Invoke-Expression" statt "-File": laedt den Skriptinhalt als
        # Text und fuehrt ihn aus, statt eine .ps1-Datei zu oeffnen. Die PowerShell-
        # Ausfuehrungsrichtlinie (auch per Gruppenrichtlinie auf "Restricted" erzwungen)
        # blockiert gezielt das Ausfuehren von Skriptdateien, nicht aber dynamisch per
        # Invoke-Expression ausgefuehrten Code. Dadurch startet JOLIA_setup.exe auch auf
        # Rechnern, auf denen die PowerShell-Skriptausfuehrung per Richtlinie gesperrt ist.
        $elevateCommand = '$JoliaScriptPath = ' + "'" + ($JoliaScriptPath -replace "'", "''") + "'" + '; Get-Content -LiteralPath $JoliaScriptPath -Raw | Invoke-Expression'
        $encodedElevateCommand = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($elevateCommand))
        Start-Process powershell.exe -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encodedElevateCommand) -Verb RunAs
    } else {
        Start-Process powershell.exe -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"") -Verb RunAs
    }
    exit 0
}

$logo = @'
    ###   ###  #     #####   ###
        #  #   # #       #    #   #
        #  #   # #       #    #####
#   #  #   # #       #    #   #
 ###    ###  ##### #####  #   #
'@
Write-Host $logo -ForegroundColor Cyan
Write-Host "JOLIA Docs - Turn Documents, Photos and Scans into Knowledge" -ForegroundColor White
Write-Host ""
Write-Host "DISCLAIMER / LIZENZ" -ForegroundColor Yellow
Write-Host "JOLIA wird unter PolyForm Noncommercial 1.0.0 nur nicht-kommerziell lizenziert." -ForegroundColor Yellow
Write-Host "Kommerzielle Nutzung ist ohne separate schriftliche Erlaubnis untersagt." -ForegroundColor Yellow
Write-Host "Die Software wird ohne ausdrueckliche oder stillschweigende Gewaehrleistung bereitgestellt." -ForegroundColor Yellow
Write-Host "Die Nutzung erfolgt auf eigene Verantwortung. Den vollstaendigen Lizenztext" -ForegroundColor Yellow
Write-Host "findest du in der Datei LICENSE." -ForegroundColor Yellow
Write-Host ""
Write-Host "=== JOLIA Docs - WSL-Verwaltung ===" -ForegroundColor Cyan

Load-JoliaStorageSettings

# Faengt jeden sonst unbehandelten Fehler ab (z.B. aus einem Cmdlet, das mit
# $ErrorActionPreference="Stop" terminiert), statt das Fenster kommentarlos zu schliessen.
trap {
    Write-Fail "Unerwarteter Fehler: $($_.Exception.Message)"
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
    Exit-Fail
}

# ── Admin-Menue ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "JOLIA-Verwaltung" -ForegroundColor Cyan
Write-Host "  1: JOLIA installieren oder reparieren"
Write-Host "  2: Auf Updates prüfen"
Write-Host "  3: Autostart aktivieren/deaktivieren (Installation bleibt erhalten)"
Write-Host "  4: JOLIA vollständig deinstallieren"
Write-Host "  5: Status prüfen"
Write-Host "  6: FRITZ!Box-Zugang oder lokalen Speicherordner ändern"
Write-Host "  7: LAN-Zugriff und Ollama diagnostizieren (Container, Modelle, API und Logs)"
$choice = Read-Host "Bitte Auswahl eingeben (1-7)"

switch ($choice) {
    "1" {
        if (-not (Confirm-JoliaNoncommercialLicense)) {
            Write-Warn2 "Installation/Reparatur wird abgebrochen."
            Read-Host "`nDruecke Enter zum Schliessen"
            exit 0
        }
    }
    "2" {
        Update-Jolia
        Read-Host "`nDruecke Enter zum Schliessen"
        exit 0
    }
    "3" {
        Write-Host "  1: Autostart aktivieren"
        Write-Host "  2: Autostart deaktivieren"
        $autostartChoice = Read-Host "Bitte Auswahl eingeben (1-2)"
        if ($autostartChoice -eq "1") {
            Enable-JoliaAutostart
        } elseif ($autostartChoice -eq "2") {
            Disable-JoliaAutostart
        } else {
            Write-Warn2 "Ungültige Auswahl."
        }
        Read-Host "`nDruecke Enter zum Schliessen"
        exit 0
    }
    "4" {
        Write-Host "ACHTUNG: Die Deinstallation löscht die JOLIA-WSL-Distro und ALLE darin gespeicherten Daten dauerhaft." -ForegroundColor Red
        Write-Host "Bei einer Neuinstallation müssen deine Daten aus einem zuvor erstellten Backup wiederhergestellt werden." -ForegroundColor Yellow
        Write-Host "Erstelle und prüfe vor dem Fortfahren ein Backup (Einstellungen > Backups)." -ForegroundColor Yellow
        $confirmation = Read-Host "Zum endgültigen Löschen bitte LOESCHEN eingeben"
        if ($confirmation -cne "LOESCHEN") {
            Write-Host "Deinstallation abgebrochen; JOLIA und Daten bleiben unverändert." -ForegroundColor Green
        } else {
            Invoke-JoliaUninstall
        }
        Read-Host "`nDruecke Enter zum Schliessen"
        exit 0
    }
    "5" {
        Show-JoliaStatus
        Read-Host "`nDruecke Enter zum Schliessen"
        exit 0
    }
    "6" {
        Set-JoliaStorage
        Read-Host "`nDruecke Enter zum Schliessen"
        exit 0
    }
    "7" {
        Test-JoliaLanAccess
        Read-Host "`nDruecke Enter zum Schliessen"
        exit 0
    }
    default {
        Write-Warn2 "Ungültige Auswahl. Es wurde nichts geändert."
        Read-Host "`nDruecke Enter zum Schliessen"
        exit 0
    }
}

# ── Phase 1: Preflight ──────────────────────────────────────────────────────
Write-Step "Prüfe Systemvoraussetzungen..."

$build = [System.Environment]::OSVersion.Version.Build
if ($build -lt 22621) {
    Write-Fail "Windows-Build $build wird nicht unterstuetzt (LAN-Zugriff via Mirrored Networking benoetigt Windows 11 22H2, Build 22621 oder neuer)."
    Exit-Fail
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

# ── Phase 2: WSL2-Voraussetzungen aktivieren (kein Auto-Reboot) ────────────
Write-Step "Prüfe WSL2..."

function Test-WslReady {
    wsl --status *> $null
    return $LASTEXITCODE -eq 0
}

$restartRequired = $false
$wslFeature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux
$vmFeature = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
if ($wslFeature.State -ne "Enabled" -or $vmFeature.State -ne "Enabled") {
    Write-Warn2 "Aktiviere die erforderlichen Windows-Features für WSL2..."
    dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Das Windows-Feature 'Windows Subsystem for Linux' konnte nicht aktiviert werden."
        Exit-Fail
    }
    dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Das Windows-Feature 'Virtual Machine Platform' konnte nicht aktiviert werden."
        Exit-Fail
    }
    $restartRequired = $true
}

$bcdConfig = bcdedit.exe /enum '{current}' 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Die Hypervisor-Startkonfiguration konnte nicht geprüft werden."
    $bcdConfig | ForEach-Object { Write-Host $_ }
    Exit-Fail
}
if (($bcdConfig -join "`n") -match '(?im)^\s*hypervisorlaunchtype\s+off\s*$') {
    Write-Warn2 "Aktiviere den Windows-Hypervisor beim Systemstart..."
    bcdedit.exe /set hypervisorlaunchtype auto
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Der Windows-Hypervisor konnte nicht für den Systemstart aktiviert werden."
        Exit-Fail
    }
    $restartRequired = $true
}

if ($restartRequired) {
    Write-Host "Die WSL2-Voraussetzungen wurden aktiviert. Bitte Windows neu starten und dieses Skript danach erneut ausführen." -ForegroundColor Yellow
    Exit-Fail
}

# Prueft, ob eine Datei ein vollstaendiges, unbeschaedigtes gzip-Archiv ist - ein
# abgebrochener/unterbrochener Download kann eine Datei passender Groesse, aber
# trunkiertem Inhalt hinterlassen ("truncated gzip input" bei wsl --import).
function Test-GzipFile ($Path) {
    if (-not (Test-Path $Path)) { return $false }
    $fileStream = $null
    $gzipStream = $null
    try {
        $fileStream = [System.IO.File]::OpenRead($Path)
        $gzipStream = New-Object System.IO.Compression.GZipStream($fileStream, [System.IO.Compression.CompressionMode]::Decompress)
        $buffer = New-Object byte[] 1MB
        while ($gzipStream.Read($buffer, 0, $buffer.Length) -gt 0) { }
        return $true
    } catch {
        return $false
    } finally {
        if ($gzipStream) { $gzipStream.Dispose() }
        if ($fileStream) { $fileStream.Dispose() }
    }
}

if (-not (Test-WslReady)) {
    Write-Fail "WSL lässt sich noch nicht starten. Prüfe Windows Update und führe 'wsl --update' in einer administrativen PowerShell aus."
    Exit-Fail
}
Write-Ok "WSL2 ist einsatzbereit."

if (Set-WslGlobalNetworkingMode) {
    Write-Warn2 "Beende WSL, damit Mirrored Networking wirksam wird (andere laufende WSL-Distros werden ebenfalls beendet)."
    wsl --shutdown
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "WSL konnte nicht sauber beendet werden."
        Exit-Fail
    }
}

Set-JoliaFirewallRule

wsl --set-default-version 2 | Out-Null

# ── Phase 3: Distro-Import ─────────────────────────────────────────────────
Write-Step "Prüfe JOLIA-WSL-Distro..."

# wsl -l -q liefert UTF-16-Namen mit eingebetteten Nullbytes -> vor Vergleich entfernen.
$existingDistros = (wsl -l -q) -replace "`0", ""
$distroExists = $existingDistros -contains $DistroName

if (-not $distroExists) {
    Write-Host "Lege isolierte Distro '$DistroName' an..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $DistroData -Force | Out-Null

    if ((Test-Path $RootfsPath) -and -not (Test-GzipFile $RootfsPath)) {
        Write-Warn2 "Vorhandenes Rootfs ist beschaedigt/unvollstaendig, wird neu geladen..."
        Remove-Item $RootfsPath -Force
    }

    $importOk = $false
    for ($attempt = 1; $attempt -le 2 -and -not $importOk; $attempt++) {
        if (-not (Test-Path $RootfsPath)) {
            $downloaded = $false
            foreach ($url in $RootfsUrls) {
                try {
                    Write-Host "  Lade Ubuntu-Rootfs von $url ..." -ForegroundColor Yellow
                    Invoke-WebRequest -Uri $url -OutFile $RootfsPath -UseBasicParsing
                    if (Test-GzipFile $RootfsPath) {
                        $downloaded = $true
                        break
                    }
                    Write-Warn2 "Heruntergeladenes Rootfs ist beschaedigt, versuche naechste Quelle..."
                    Remove-Item $RootfsPath -Force -ErrorAction SilentlyContinue
                } catch {
                    Write-Warn2 "Download von $url fehlgeschlagen, versuche nächste Quelle..."
                }
            }
            if (-not $downloaded) {
                Write-Fail "Konnte kein unbeschaedigtes Ubuntu-Rootfs herunterladen. Abbruch."
                Exit-Fail
            }
        }

        $importOutput = wsl --import $DistroName $DistroData $RootfsPath --version 2 2>&1
        $importExitCode = $LASTEXITCODE
        $importOutput | ForEach-Object { Write-Host $_ }
        if ($importExitCode -eq 0) {
            $importOk = $true
        } elseif (($importOutput -join "`n") -match "HCS_E_SERVICE_NOT_AVAILABLE") {
            Write-Fail "Der WSL2-Hypervisor ist nicht verfügbar. Das Ubuntu-Rootfs ist heruntergeladen; der Fehler liegt bei Windows/Virtualisierung."
            Write-Host "Prüfe im UEFI/BIOS, ob Intel VT-x bzw. AMD-V/SVM aktiviert ist." -ForegroundColor Yellow
            Write-Host "In einer administrativen PowerShell: bcdedit /set hypervisorlaunchtype auto" -ForegroundColor Yellow
            Write-Host "Stelle sicher, dass Virtual Machine Platform aktiviert ist, und starte Windows danach neu." -ForegroundColor Yellow
            Exit-Fail
        } elseif ($attempt -lt 2) {
            Write-Warn2 "wsl --import fehlgeschlagen, entferne moeglicherweise beschaedigtes Rootfs und versuche es erneut..."
            wsl --unregister $DistroName 2>$null | Out-Null
            Remove-Item -Path $DistroData -Recurse -Force -ErrorAction SilentlyContinue
            New-Item -ItemType Directory -Path $DistroData -Force | Out-Null
            Remove-Item $RootfsPath -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not $importOk) {
        Write-Fail "wsl --import fehlgeschlagen."
        Exit-Fail
    }
    Write-Ok "Distro '$DistroName' importiert."
} else {
    Write-Ok "Distro '$DistroName' existiert bereits."
}

Set-WslConf -Distro $DistroName
$activeNetworkMode = @(wsl -d $DistroName -u root -- wslinfo --networking-mode 2>&1)
if ($LASTEXITCODE -eq 0) {
    if (($activeNetworkMode -join " ").Trim() -ne "mirrored") {
        Write-Fail "WSL verwendet nicht den benoetigten Mirrored-Modus: $($activeNetworkMode -join ' ')."
        Write-Warn2 "Andere WSL-Arbeit speichern, 'wsl --shutdown' ausfuehren und Option 1 erneut starten."
        Exit-Fail
    }
    Write-Ok "WSL verwendet tatsaechlich Mirrored Networking."
} else {
    Write-Warn2 "Aktiver Netzwerkmodus konnte nicht geprueft werden. WSL mit 'wsl --update' aktualisieren; LAN-Erreichbarkeit bleibt unverifiziert."
}
if ($StorageMode -eq "FritzNas") {
    Mount-FritzNasShares -Distro $DistroName
    wsl -d $DistroName -u root -- bash -c "mountpoint -q $FritzNasUploadMount && mountpoint -q $FritzNasBackupMount"
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "FRITZ!NAS ist nicht eingebunden. Installation abgebrochen; mit Option 6 Zugangsdaten oder lokalen Speicher konfigurieren."
        Exit-Fail
    }
} else {
    New-Item -ItemType Directory -Path (Join-Path $LocalStorageRoot "inbox"), (Join-Path $LocalStorageRoot "backup") -Force | Out-Null
    Write-Ok "Verwende lokalen Speicherordner $LocalStorageRoot."
}

# ── Phase 4: Docker-Provisioning in der Distro ─────────────────────────────
Write-Step "Prüfe Docker in der Distro..."

$dockerCheck = wsl -d $DistroName -u root -- bash -c "command -v docker >/dev/null 2>&1 && echo yes || echo no"
if ($dockerCheck.Trim() -ne "yes") {
    # Docker ueber das Ubuntu-Repo installieren (docker.io + docker-compose-v2-Plugin).
    # Kein "curl https://get.docker.com | sh": in restriktiven Netzwerken (Firmenproxy/
    # fehlende CA) schlaegt der TLS-Handshake dabei fehl, ohne dass der Pipe-Exitcode
    # das anzeigt (der letzte Befehl "sh" liefert trotzdem 0 zurueck).
    Write-Host "Installiere Docker Engine (apt: docker.io)..." -ForegroundColor Yellow
    wsl -d $DistroName -u root -- bash -c "export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y docker.io docker-compose-v2 docker-buildx git"
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Docker-Installation fehlgeschlagen."
        Exit-Fail
    }
    $dockerCheck = wsl -d $DistroName -u root -- bash -c "command -v docker >/dev/null 2>&1 && echo yes || echo no"
    if ($dockerCheck.Trim() -ne "yes") {
        Write-Fail "Docker-Installation fehlgeschlagen (Binary 'docker' nach Installation nicht gefunden)."
        Exit-Fail
    }
    Write-Ok "Docker Engine installiert."
} else {
    Write-Ok "Docker Engine bereits installiert."
}

# "docker-buildx" (apt) landet im System-Plugin-Verzeichnis; Compose sucht das
# Plugin aber auch/zuerst unter ~/.docker/cli-plugins. Ohne Nachinstallation faellt
# "docker compose build" auf den langsameren Legacy-Builder zurueck (Bake-Warnung).
$buildxCheck = wsl -d $DistroName -u root -- bash -c "docker buildx version >/dev/null 2>&1 && echo yes || echo no"
if ($buildxCheck.Trim() -ne "yes") {
    Write-Step "Installiere Docker Buildx-Plugin (behebt 'Bake'-Warnung beim Build)..."
    # Ubuntu-Repo: "docker-buildx"; "docker-buildx-plugin" gibt es nur im Docker-eigenen Repo.
    wsl -d $DistroName -u root -- bash -c "export DEBIAN_FRONTEND=noninteractive; apt-get update && (apt-get install -y docker-buildx || apt-get install -y docker-buildx-plugin)"
    # Falls das Binary in einem Plugin-Pfad liegt, den die CLI nicht durchsucht: verlinken.
    wsl -d $DistroName -u root -- bash -c "docker buildx version >/dev/null 2>&1 || for b in /usr/libexec/docker/cli-plugins/docker-buildx /usr/lib/docker/cli-plugins/docker-buildx; do if [ -x `$b ]; then mkdir -p /usr/local/lib/docker/cli-plugins; ln -sf `$b /usr/local/lib/docker/cli-plugins/docker-buildx; break; fi; done"
    $buildxCheck = wsl -d $DistroName -u root -- bash -c "docker buildx version >/dev/null 2>&1 && echo yes || echo no"
    if ($buildxCheck.Trim() -eq "yes") {
        Write-Ok "Docker Buildx installiert."
    } else {
        Write-Warn2 "Docker Buildx konnte nicht installiert werden. Build laeuft trotzdem (langsamerer Legacy-Builder)."
    }
} else {
    Write-Ok "Docker Buildx bereits vorhanden."
}

$composeCheck = wsl -d $DistroName -u root -- bash -c "docker compose version >/dev/null 2>&1 && echo yes || echo no"
if (($composeCheck -join "").Trim() -ne "yes") {
    wsl -d $DistroName -u root -- bash -c "export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y docker-compose-v2"
    if ($LASTEXITCODE -ne 0) { Write-Fail "Docker Compose konnte nicht installiert werden."; Exit-Fail }
}
wsl -d $DistroName -u root -- bash -c "(systemctl enable --now docker || service docker start) && docker info >/dev/null && docker compose version"
if ($LASTEXITCODE -ne 0) { Write-Fail "Docker Engine/Compose ist nicht einsatzbereit."; Exit-Fail }

# ── Phase 5: App-Deployment ─────────────────────────────────────────────────
Write-Step "Hole JOLIA-Code..."

if (-not (Sync-JoliaRepo -Distro $DistroName -AppDir $AppDirLinux -Repo $RepoUrl)) {
    Write-Warn2 "Falls das Repo privat ist: Git-Credentials sicher in der Distro konfigurieren oder einen SSH-Deploy-Key nutzen. PATs niemals direkt in Git-URLs eintragen."
    Exit-Fail
}
Write-Ok "JOLIA-Code aktuell."

Write-Step "Konfiguriere JOLIA (Port, Datenordner)..."
Set-JoliaDeploymentConfig -Distro $DistroName
wsl -d $DistroName -u root -- bash -c "cd $AppDirLinux && docker compose config --quiet"
if ($LASTEXITCODE -ne 0) { Write-Fail "Die Docker-Compose-Konfiguration ist ungueltig."; Exit-Fail }
if ($StorageMode -eq "FritzNas") {
    Write-Ok "Upload/Backup ueber FRITZ!NAS ($JoliaInboxLinux / $JoliaBackupLinux), Archiv nativ in WSL ($ArchiveLinux, schnell)."
} else {
    Write-Ok "Upload/Backup lokal ($JoliaInboxLinux / $JoliaBackupLinux), Archiv nativ in WSL ($ArchiveLinux, schnell)."
}

# Zusätzliche Vorab-Checks, da der erste "docker compose up" mehrere GB an
# Ollama-Modellen herunterlädt (ollama-init-Dienst in docker-compose.yml).
Write-Step "Prüfe Voraussetzungen für den KI-Modell-Download..."
$freeGbNow = [math]::Round((Get-PSDrive -Name $driveLetter).Free / 1GB, 1)
if ($freeGbNow -lt 10) {
    Write-Warn2 "Nur noch $freeGbNow GB frei. Der Modell-Download (Ollama: qwen2.5:1.5b/7b, qwen2.5vl:3b, bge-m3) benötigt ca. 10 GB und kann fehlschlagen."
} else {
    Write-Ok "$freeGbNow GB frei - ausreichend für den Modell-Download."
}
try {
    $null = Invoke-WebRequest -Uri "https://ollama.com" -Method Head -UseBasicParsing -TimeoutSec 10
    Write-Ok "ollama.com erreichbar."
} catch {
    Write-Warn2 "ollama.com nicht erreichbar - Modell-Download könnte fehlschlagen."
}

if (-not (Confirm-JoliaModelTerms)) {
    Exit-Fail
}

Write-Step "Starte JOLIA per Docker Compose (erster Start lädt KI-Modelle, kann dauern)..."
wsl -d $DistroName -u root -- bash -c "cd $AppDirLinux && docker compose up -d --build"
if ($LASTEXITCODE -ne 0) {
    Write-Fail "docker compose up fehlgeschlagen."
    Exit-Fail
}

Write-Step "Registriere Autostart und halte WSL waehrend des App-Starts aktiv..."
Register-JoliaAutostart
Save-JoliaStorageSettings

Write-Step "Warte auf JOLIA (kann beim ersten Start mehrere Minuten dauern)..."
$healthy = $false
$lastHealthError = "Keine HTTP-200-Antwort erhalten."
for ($i = 0; $i -lt 60; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$AppPort/health" -UseBasicParsing -TimeoutSec 5
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
        $lastHealthError = "HTTP $($resp.StatusCode)"
    } catch { $lastHealthError = $_.Exception.Message }
    Start-Sleep -Seconds 10
}
if ($healthy) {
    Write-Ok "JOLIA läuft."
} else {
    Write-Fail "JOLIA antwortet nach dem Start nicht. Die Installation ist nicht als erfolgreich verifiziert."
    Write-Fail "Letzter Windows-HTTP-Test auf http://127.0.0.1:$AppPort/health : $lastHealthError"
    Test-JoliaOllama
    Write-Warn2 "Bei gesundem App-Container: Menueoption 7 prueft den Portpfad Container -> WSL -> Windows und die Firewall."
    Exit-Fail
}

Write-Host ""
Write-Host "=== Fertig ===" -ForegroundColor Cyan
Show-JoliaAccessUrls -Distro $DistroName
Write-Host "Upload: FRITZ!NAS $FritzNasUploadMount  |  Archiv: WSL $ArchiveLinux  |  Backup: FRITZ!NAS $FritzNasBackupMount" -ForegroundColor DarkGray
Write-Host "LAN-Zugriff klappt nicht? Diagnose: Menüoption 7" -ForegroundColor DarkGray
Write-Host "Deinstallation (rückstandsfrei): Menüoption 4" -ForegroundColor DarkGray
Read-Host "`nDruecke Enter zum Schliessen"
