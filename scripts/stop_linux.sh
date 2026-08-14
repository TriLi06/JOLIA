#!/usr/bin/env bash
# JOLIA Docs – Linux: App sicher stoppen
#
# Sendet SIGTERM an den laufenden uvicorn-Prozess (app.main:app), wartet auf
# einen sauberen Shutdown und erzwingt SIGKILL nur, falls er nicht rechtzeitig
# beendet.

set -e

PATTERN="uvicorn app\.main:app"

PIDS=$(pgrep -f "$PATTERN" || true)

if [ -z "$PIDS" ]; then
    echo "Keine laufende uvicorn-Instanz von app.main:app gefunden."
    exit 0
fi

echo "Sende SIGTERM an: $PIDS"
kill -TERM $PIDS

# Bis zu 10s auf sauberes Beenden warten
for i in $(seq 1 10); do
    sleep 1
    PIDS=$(pgrep -f "$PATTERN" || true)
    if [ -z "$PIDS" ]; then
        echo "JOLIA Docs gestoppt."
        exit 0
    fi
done

echo "Prozess reagiert nicht auf SIGTERM – erzwinge Beendigung (SIGKILL)."
kill -KILL $PIDS 2>/dev/null || true
echo "JOLIA Docs gestoppt."
