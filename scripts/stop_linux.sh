#!/usr/bin/env bash
# JOLIA Docs – Linux: App sicher stoppen
#
# Sendet SIGTERM an den laufenden uvicorn-Prozess (app.main:app), wartet auf
# einen sauberen Shutdown und erzwingt SIGKILL nur, falls er nicht rechtzeitig
# beendet. Anschließend wird geprüft, ob der Port wirklich frei ist.

set -e

PATTERN="uvicorn app\.main:app"
PORT="${PORT:-8080}"

# Räumt den Port ab, falls ihn noch ein verwaister Kindprozess hält.
free_port() {
    local pids=""
    if command -v ss >/dev/null 2>&1; then
        pids=$(ss -ltnpH "sport = :$PORT" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u || true)
    elif command -v lsof >/dev/null 2>&1; then
        pids=$(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null || true)
    else
        echo "  Hinweis: weder ss noch lsof vorhanden – Port $PORT nicht prüfbar."
        return 0
    fi

    if [ -z "$pids" ]; then
        echo "Port $PORT ist frei."
        return 0
    fi

    echo "Port $PORT wird noch von PID(s) $pids belegt – beende sie."
    kill -KILL $pids 2>/dev/null || true
    sleep 1
}

PIDS=$(pgrep -f "$PATTERN" || true)

if [ -z "$PIDS" ]; then
    echo "Keine laufende uvicorn-Instanz von app.main:app gefunden."
    free_port
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
        free_port
        exit 0
    fi
done

echo "Prozess reagiert nicht auf SIGTERM – erzwinge Beendigung (SIGKILL)."
kill -KILL $PIDS 2>/dev/null || true
echo "JOLIA Docs gestoppt."
free_port
