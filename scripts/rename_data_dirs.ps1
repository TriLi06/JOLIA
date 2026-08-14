# JOLIA Docs – Datenverzeichnisse umbenennen (docstoreai -> jolia)
#
# Nach dem STOPPEN der App ausführen. Benennt die alten Datenordner auf die
# neuen, von der umbenannten App erwarteten Pfade um. Idempotent und sicher:
# fehlende Quellen werden übersprungen, bereits vorhandene Ziele werden nicht
# überschrieben.

$ErrorActionPreference = "Stop"

# Alte -> neue Verzeichnisse (aus config.yaml / config.windows.yaml / .env)
$mappings = [ordered]@{
    "C:\dev\docstoreai"      = "C:\dev\jolia"
    "C:\dev\docstoreai-test" = "C:\dev\jolia-test"
}

Write-Host "=== JOLIA Docs – Datenverzeichnisse umbenennen ===" -ForegroundColor Cyan

foreach ($old in $mappings.Keys) {
    $new = $mappings[$old]

    if (-not (Test-Path -LiteralPath $old)) {
        Write-Host "  [skip]   $old existiert nicht." -ForegroundColor DarkGray
        continue
    }

    if (Test-Path -LiteralPath $new) {
        Write-Host "  [!]      Ziel existiert bereits: $new" -ForegroundColor Yellow
        Write-Host "           $old wurde NICHT umbenannt. Bitte manuell zusammenführen." -ForegroundColor Yellow
        continue
    }

    try {
        Move-Item -LiteralPath $old -Destination $new
        Write-Host "  [ok]     $old  ->  $new" -ForegroundColor Green
    }
    catch {
        Write-Host "  [error]  $old konnte nicht umbenannt werden: $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Fertig. Die App kann jetzt wieder gestartet werden." -ForegroundColor Cyan
