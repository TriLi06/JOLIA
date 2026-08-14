# JOLIA Docs – Docker: App sicher stoppen
#
# Stoppt die Container (app, ollama, ollama-init) sauber, ohne sie oder die
# Volumes zu entfernen. Mit "docker compose up -d" (bzw. "docker compose
# start") lässt sich der Stand danach wieder starten.

$ErrorActionPreference = "Stop"

Write-Host "=== JOLIA Docs – Docker-Container stoppen ===" -ForegroundColor Cyan
docker compose stop
Write-Host "Container gestoppt (Daten/Volumes bleiben erhalten)." -ForegroundColor Green
