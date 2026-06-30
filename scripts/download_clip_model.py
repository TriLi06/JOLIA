"""
Lädt das ViT-B/32 CLIP-Modell von OpenAI's Azure-CDN herunter (kein Hugging Face nötig).
Speichert es unter data/models/ViT-B-32.pt im Projektverzeichnis.

Verwendung:
    python scripts/download_clip_model.py

Danach in config.yaml setzen:
    models:
      clip_backend: "openclip"
      clip_model: "ViT-B-32"
      clip_pretrained: "data/models/ViT-B-32.pt"   # oder absoluter Pfad
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Verfügbare Modelle (von https://openaipublic.azureedge.net/clip/models/)
# ---------------------------------------------------------------------------
MODELS = {
    "ViT-B-32": {
        "url": "https://openaipublic.azureedge.net/clip/models/"
               "40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af/ViT-B-32.pt",
        "sha256": "40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af",
        "size_mb": 338,
    },
    "ViT-B-16": {
        "url": "https://openaipublic.azureedge.net/clip/models/"
               "5806520817d4a2fd46d255d3a784eb21f955c4e0ed82571f02921f18bdc58ade/ViT-B-16.pt",
        "sha256": "5806520817d4a2fd46d255d3a784eb21f955c4e0ed82571f02921f18bdc58ade",
        "size_mb": 335,
    },
    "ViT-L-14": {
        "url": "https://openaipublic.azureedge.net/clip/models/"
               "b8cca3fd41ae0c99ba7e8951adf17d267cdb84cd88be6f7c2e0eca1737a03836/ViT-L-14.pt",
        "sha256": "b8cca3fd41ae0c99ba7e8951adf17d267cdb84cd88be6f7c2e0eca1737a03836",
        "size_mb": 890,
    },
    "RN50": {
        "url": "https://openaipublic.azureedge.net/clip/models/"
               "afeb0e10f9e5a86da6080e35cf09123aca3b358a0c3e3b6c78a7b63bc04b6762/RN50.pt",
        "sha256": "afeb0e10f9e5a86da6080e35cf09123aca3b358a0c3e3b6c78a7b63bc04b6762",
        "size_mb": 102,
    },
}

DEFAULT_MODEL = "ViT-B-32"


def verify_sha256(path: Path, expected: str) -> bool:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest() == expected


def download_with_progress(url: str, dest: Path) -> None:
    def _hook(count, block_size, total_size):
        if total_size > 0:
            pct = min(100, count * block_size * 100 // total_size)
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            print(f"\r  [{bar}] {pct:3d}%", end="", flush=True)

    urllib.request.urlretrieve(url, dest, reporthook=_hook)
    print()  # Zeilenumbruch nach Fortschrittsbalken


def main() -> None:
    # Zielverzeichnis (relativ zum Skript-Verzeichnis: Projekt-Root/data/models/)
    project_root = Path(__file__).parent.parent
    models_dir = project_root / "data" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    model_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    if model_name not in MODELS:
        print(f"Unbekanntes Modell: {model_name}")
        print(f"Verfügbare Modelle: {', '.join(MODELS)}")
        sys.exit(1)

    info = MODELS[model_name]
    dest = models_dir / f"{model_name}.pt"

    print(f"Modell:       {model_name}")
    print(f"Größe:        ~{info['size_mb']} MB")
    print(f"Quelle:       OpenAI Azure CDN (kein Hugging Face)")
    print(f"Ziel:         {dest}")
    print()

    if dest.exists():
        print("Datei bereits vorhanden – verifiziere SHA256 …")
        if verify_sha256(dest, info["sha256"]):
            print("✅ SHA256 korrekt, kein Download nötig.")
        else:
            print("⚠️  SHA256-Mismatch – lade erneut herunter …")
            dest.unlink()
        if dest.exists():
            _print_config_hint(model_name, dest)
            return

    print(f"Lade herunter von:\n  {info['url']}\n")
    try:
        download_with_progress(info["url"], dest)
    except Exception as exc:
        print(f"\n❌ Download fehlgeschlagen: {exc}")
        if dest.exists():
            dest.unlink()
        sys.exit(1)

    print("Verifiziere SHA256 …")
    if not verify_sha256(dest, info["sha256"]):
        print("❌ SHA256-Prüfung fehlgeschlagen – Datei beschädigt!")
        dest.unlink()
        sys.exit(1)

    print(f"✅ Download erfolgreich: {dest}")
    _print_config_hint(model_name, dest)


def _print_config_hint(model_name: str, dest: Path) -> None:
    print(f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Füge folgendes in config.yaml ein um OpenCLIP zu aktivieren:

  models:
    clip_backend: "openclip"
    clip_model: "{model_name}"
    clip_pretrained: "{dest.as_posix()}"
    enable_clip_embeddings: true  # in processing-Sektion

Hinweis: Bestehende Bilder müssen neu verarbeitet werden damit
         OpenCLIP-Embeddings erstellt werden.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")


if __name__ == "__main__":
    main()
