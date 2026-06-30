# DocScan PWA – Entwicklungsserver starten
# Voraussetzung: Node.js >= 18, npm >= 9

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pwaDir = Join-Path $scriptDir "..\docscan-pwa"

Write-Host "DocScan PWA Dev-Server wird gestartet..." -ForegroundColor Cyan
Write-Host "Backend-URL: http://localhost:8080 (muss separat gestartet sein)" -ForegroundColor Yellow
Write-Host ""

Set-Location $pwaDir
npm run dev
