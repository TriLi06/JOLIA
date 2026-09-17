#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

# Nur die Modelldateien vorbereiten. Ollama lädt das Modell erst beim ersten
# tatsächlichen Generate-/Embed-Aufruf in den Speicher.
if command -v ollama >/dev/null 2>&1; then
	if ! curl -fsS --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
		ollama serve >/tmp/jolia-ollama.log 2>&1 &
		for _ in $(seq 1 15); do
			curl -fsS --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1 && break
			sleep 1
		done
	fi
	for model in qwen2.5:3b qwen2.5:7b minicpm-v bge-m3; do
		if ! ollama list | awk 'NR > 1 {print $1}' | grep -Fxq "$model"; then
			echo "Lade Ollama-Modell herunter: $model"
			ollama pull "$model"
		fi
	done
else
	echo "WARNUNG: ollama nicht gefunden; Ollama-Modelle werden nicht vorbereitet." >&2
fi

source .venv/bin/activate
exec uvicorn app.main:app --host 0.0.0.0 --port 8080
