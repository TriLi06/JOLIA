#!/usr/bin/env bash
# JOLIA Docs – Docker: App sicher stoppen
#
# Stoppt die Container (app, ollama, ollama-init) sauber, ohne sie oder die
# Volumes zu entfernen. Mit "docker compose up -d" (bzw. "docker compose
# start") lässt sich der Stand danach wieder starten.

set -e

echo "=== JOLIA Docs – Docker-Container stoppen ==="
docker compose stop
echo "Container gestoppt (Daten/Volumes bleiben erhalten)."
