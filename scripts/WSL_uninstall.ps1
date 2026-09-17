# JOLIA Docs – rückstandsfreie Deinstallation der WSL-Installation
#
# Entfernt den Autostart-Task und die komplette isolierte WSL-Distro
# "jolia-wsl" (inkl. aller Docker-Images/-Volumes und des geklonten Repos)
# sowie den Installationsordner. Gegenstück zu scripts\WSL_startup.ps1.

$ErrorActionPreference = "Stop"

$DistroName  = "jolia-wsl"
$InstallRoot = "C:\JOLIA-WSL"
$TaskName    = "JOLIA-WSL-Autostart"

$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Starte Skript mit Administratorrechten neu..." -ForegroundColor Yellow
    Start-Process powershell.exe -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"") -Verb RunAs
    exit 0
}

Write-Host "=== JOLIA Docs - WSL-Deinstallation ===" -ForegroundColor Cyan

Write-Host "Entferne Autostart-Task..." -ForegroundColor Yellow
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "  erledigt." -ForegroundColor Green

$existingDistros = (wsl -l -q) -replace "`0", ""
if ($existingDistros -contains $DistroName) {
    Write-Host "Entferne WSL-Distro '$DistroName' (inkl. aller Container/Images/Volumes/Code)..." -ForegroundColor Yellow
    wsl --unregister $DistroName
    Write-Host "  erledigt." -ForegroundColor Green
} else {
    Write-Host "Distro '$DistroName' existiert nicht (mehr)." -ForegroundColor DarkGray
}

if (Test-Path $InstallRoot) {
    Write-Host "Lösche Installationsordner $InstallRoot..." -ForegroundColor Yellow
    Remove-Item -Path $InstallRoot -Recurse -Force
    Write-Host "  erledigt." -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Fertig ===" -ForegroundColor Cyan
Write-Host "JOLIA und alle zugehörigen Daten wurden entfernt." -ForegroundColor Green
Write-Host "Hinweis: Die Windows-Features 'Windows-Subsystem für Linux' und" -ForegroundColor DarkGray
Write-Host "'Virtual Machine Platform' bleiben aktiviert (werden ggf. von anderen" -ForegroundColor DarkGray
Write-Host "WSL-Distros/Tools benutzt). Manuell deaktivierbar via:" -ForegroundColor DarkGray
Write-Host "  dism /online /disable-feature /featurename:Microsoft-Windows-Subsystem-Linux" -ForegroundColor DarkGray
Write-Host "  dism /online /disable-feature /featurename:VirtualMachinePlatform" -ForegroundColor DarkGray
