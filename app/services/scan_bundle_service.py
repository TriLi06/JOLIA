"""
Scan-Bundles: Mehrere Einzelbilder aus der Inbox werden zu EINEM PDF mit
durchsuchbarem Textlayer zusammengefasst.

Konvention (gilt fuer alle Quellen: PWA-Live-Kamera, Kamera-App, Web-Formular
und externe Apps wie die geplante Kotlin-App):

  Seitendatei : {bundle_id}_{NN}.{jpg|jpeg|png|heic|webp|tif}
                bundle_id = UUID (mit oder ohne Bindestriche), NN = Seitennummer
  Manifest    : {bundle_id}.scan.json   (optional)
                {"bundle_id":..., "title":..., "source":..., "expected_pages":n,
                 "complete": true|false, "created_at": iso}
  Ergebnis    : {titel}__{bundle_id}.pdf  (landet in der Inbox und wird von der
                normalen Ingestion als ganz normales PDF importiert)

Ein Bundle ist fertig, wenn das Manifest `complete: true` gesetzt hat oder wenn
seit der letzten empfangenen Seite `scan.bundle_idle_seconds` vergangen sind
(fuer Quellen ohne Manifest).

Die Seitenbilder wandern beim Buendeln nach `temp_dir/scan_bundles/{bundle_id}/`
und werden dort erst nach der Verarbeitung des PDFs geloescht - dazwischen
nutzt der PdfProcessor sie fuer die Ollama-Vision-Analyse pro Seite.
"""
from __future__ import annotations

import io
import json
import logging
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.config import Config

logger = logging.getLogger(__name__)

PAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp"}
MANIFEST_SUFFIX = ".scan.json"
BUNDLE_META_FILENAME = "bundle.json"
BUNDLE_TEMP_DIRNAME = "scan_bundles"
TITLE_SEPARATOR = "__"

# UUID mit oder ohne Bindestriche - bewusst streng, damit normale Fotos wie
# "IMG_20240101_01.jpg" nicht versehentlich als Scan-Seite gelten.
_BUNDLE_ID_PATTERN = r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}"
_PAGE_NAME_RE = re.compile(rf"^(?P<bundle>{_BUNDLE_ID_PATTERN})_(?P<index>\d{{1,3}})$")
_BUNDLE_ID_RE = re.compile(rf"^{_BUNDLE_ID_PATTERN}$")
_UNSAFE_TITLE_CHARS = re.compile(r"[^\w \-.äöüÄÖÜß]", re.UNICODE)

# A4-Hoehe in Zoll - daraus wird die PDF-Seitengroesse abgeleitet, wenn scan.pdf_dpi = 0.
_A4_LONG_EDGE_INCHES = 11.69


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

@dataclass
class ScanBundle:
    bundle_id: str
    pages: list[tuple[int, Path]] = field(default_factory=list)
    manifest: dict | None = None
    manifest_path: Path | None = None

    @property
    def title(self) -> str | None:
        if self.manifest:
            value = str(self.manifest.get("title") or "").strip()
            if value:
                return value
        return None

    @property
    def source(self) -> str:
        if self.manifest:
            return str(self.manifest.get("source") or "unknown")
        return "inbox"

    @property
    def is_complete_flagged(self) -> bool:
        return bool(self.manifest and self.manifest.get("complete"))

    @property
    def newest_mtime(self) -> float:
        return max((p.stat().st_mtime for _, p in self.pages), default=0.0)


# ---------------------------------------------------------------------------
# Namenskonvention
# ---------------------------------------------------------------------------

def new_bundle_id() -> str:
    return uuid.uuid4().hex


def is_valid_bundle_id(value: str) -> bool:
    return bool(_BUNDLE_ID_RE.match(value or ""))


def parse_page_name(path: Path) -> tuple[str, int] | None:
    """Zerlegt einen Seitendateinamen in (bundle_id, seitennummer)."""
    if path.suffix.lower() not in PAGE_EXTENSIONS:
        return None
    match = _PAGE_NAME_RE.match(path.stem)
    if not match:
        return None
    return match.group("bundle"), int(match.group("index"))


def page_filename(bundle_id: str, index: int, extension: str) -> str:
    ext = extension if extension.startswith(".") else f".{extension}"
    return f"{bundle_id}_{index:02d}{ext.lower()}"


def is_scan_page(path: Path) -> bool:
    return parse_page_name(path) is not None


def manifest_path_for(inbox: Path, bundle_id: str) -> Path:
    return inbox / f"{bundle_id}{MANIFEST_SUFFIX}"


def bundle_id_from_pdf_name(filename: str) -> str | None:
    """Liest die bundle_id aus dem Namen eines gebuendelten PDFs zurueck."""
    stem = Path(filename).stem
    if TITLE_SEPARATOR not in stem:
        return None
    candidate = stem.rsplit(TITLE_SEPARATOR, 1)[1]
    return candidate if is_valid_bundle_id(candidate) else None


def sanitize_title(title: str | None, cfg: Config) -> str:
    raw = (title or "").strip()
    if not raw:
        raw = f"{cfg.scan.default_title_prefix}_{datetime.now():%Y-%m-%d_%H%M}"
    safe = _UNSAFE_TITLE_CHARS.sub("_", raw)
    safe = re.sub(r"_{2,}", "_", safe).strip(" ._-")
    return safe[:60] or "Scan"


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def read_manifest(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Scan-Manifest nicht lesbar (%s): %s", path.name, exc)
        return None


def write_manifest(
    inbox: Path,
    bundle_id: str,
    *,
    title: str | None = None,
    source: str | None = None,
    complete: bool = False,
    expected_pages: int | None = None,
) -> Path:
    """Legt das Manifest an oder aktualisiert es (bestehende Werte bleiben erhalten)."""
    path = manifest_path_for(inbox, bundle_id)
    data = read_manifest(path) if path.exists() else None
    data = data or {"bundle_id": bundle_id, "created_at": datetime.now().isoformat()}
    if title:
        data["title"] = title
    if source:
        data["source"] = source
    if expected_pages is not None:
        data["expected_pages"] = expected_pages
    data["complete"] = complete
    data["updated_at"] = datetime.now().isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Bundles einsammeln
# ---------------------------------------------------------------------------

def collect_bundles(inbox: Path) -> list[ScanBundle]:
    """Gruppiert alle Scan-Seiten der Inbox nach bundle_id."""
    if not inbox.exists():
        return []

    bundles: dict[str, ScanBundle] = {}
    manifests: dict[str, Path] = {}

    for entry in inbox.iterdir():
        if not entry.is_file():
            continue
        if entry.name.endswith(MANIFEST_SUFFIX):
            manifests[entry.name[: -len(MANIFEST_SUFFIX)]] = entry
            continue
        parsed = parse_page_name(entry)
        if parsed is None:
            continue
        bundle_id, index = parsed
        bundles.setdefault(bundle_id, ScanBundle(bundle_id=bundle_id)).pages.append((index, entry))

    for bundle_id, path in manifests.items():
        bundle = bundles.setdefault(bundle_id, ScanBundle(bundle_id=bundle_id))
        bundle.manifest_path = path
        bundle.manifest = read_manifest(path)

    result = []
    for bundle in bundles.values():
        if not bundle.pages:
            continue
        bundle.pages.sort(key=lambda item: (item[0], item[1].name))
        result.append(bundle)
    return result


def _is_stable(path: Path, min_age_seconds: float) -> bool:
    from app.services.watcher_service import is_file_stable

    return is_file_stable(path, min_age_seconds)


def is_ready(bundle: ScanBundle, cfg: Config) -> bool:
    """Bundle ist fertig, wenn das Manifest es sagt oder lange nichts mehr kam."""
    if not bundle.pages:
        return False
    if bundle.is_complete_flagged:
        return all(_is_stable(p, 0.0) for _, p in bundle.pages)
    expected = (bundle.manifest or {}).get("expected_pages")
    if expected:
        if len(bundle.pages) < int(expected):
            return False
        return all(_is_stable(p, 0.0) for _, p in bundle.pages)
    idle = max(cfg.scan.bundle_idle_seconds, 1)
    return all(_is_stable(p, idle) for _, p in bundle.pages)


# ---------------------------------------------------------------------------
# PDF-Erzeugung
# ---------------------------------------------------------------------------

def _open_image(path: Path):
    from PIL import Image, ImageOps

    try:
        import pillow_heif  # type: ignore

        pillow_heif.register_heif_opener()
    except Exception:
        pass

    img = Image.open(path)
    img = ImageOps.exif_transpose(img) or img
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


def _effective_dpi(img, cfg: Config) -> int:
    if cfg.scan.pdf_dpi > 0:
        return cfg.scan.pdf_dpi
    long_edge = max(img.width, img.height)
    return max(50, min(600, round(long_edge / _A4_LONG_EDGE_INCHES)))


def _tesseract_available() -> bool:
    try:
        import pytesseract

        ensure_tesseract()
        pytesseract.get_tesseract_version()
        return True
    except Exception as exc:
        logger.warning("Tesseract nicht verfuegbar (%s) - PDF wird ohne Textlayer erzeugt.", exc)
        return False


# Windows-Installer (winget/UB-Mannheim) setzen den PATH erst in einer neuen Shell.
_WINDOWS_TESSERACT_DIRS = (
    r"C:\Program Files\Tesseract-OCR",
    r"C:\Program Files (x86)\Tesseract-OCR",
)


def ensure_tesseract() -> str | None:
    """Sucht die Tesseract-Binary und meldet sie global an pytesseract.

    Gibt den Pfad zurueck oder None. Wirkt fuer die gesamte Anwendung, da
    pytesseract seinen Binary-Pfad modulweit haelt (auch fuer die Bild-OCR).
    """
    import shutil

    try:
        import pytesseract
    except ImportError:
        return None

    found = shutil.which("tesseract")
    if not found:
        for directory in _WINDOWS_TESSERACT_DIRS:
            candidate = Path(directory) / "tesseract.exe"
            if candidate.exists():
                found = str(candidate)
                break

    if found:
        pytesseract.pytesseract.tesseract_cmd = found
    return found


def build_searchable_pdf(
    images: list[Path], out_path: Path, cfg: Config
) -> tuple[list[str], bool]:
    """Baut aus den Bildern ein PDF und gibt (Text pro Seite, Textlayer vorhanden) zurueck.

    Mit Tesseract entsteht pro Seite ein unsichtbarer, markierbarer Textlayer.
    Ohne Tesseract wird ein reines Bild-PDF erzeugt (Text kommt dann nur aus der
    Vision-Analyse in den Suchindex).
    """
    use_ocr = cfg.scan.pdf_ocr and _tesseract_available()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if use_ocr:
        return _build_pdf_with_textlayer(images, out_path, cfg)
    return _build_image_only_pdf(images, out_path, cfg), False


def _build_pdf_with_textlayer(
    images: list[Path], out_path: Path, cfg: Config
) -> tuple[list[str], bool]:
    import pytesseract
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    texts: list[str] = []
    for image_path in images:
        img = _open_image(image_path)
        try:
            page_pdf = pytesseract.image_to_pdf_or_hocr(
                img,
                lang=cfg.processing.ocr_languages,
                extension="pdf",
                config=f"--dpi {_effective_dpi(img, cfg)}",
            )
        finally:
            img.close()
        reader = PdfReader(io.BytesIO(page_pdf))
        for page in reader.pages:
            writer.add_page(page)
            texts.append((page.extract_text() or "").strip())

    with out_path.open("wb") as fh:
        writer.write(fh)
    return texts, True


def _build_image_only_pdf(images: list[Path], out_path: Path, cfg: Config) -> list[str]:
    from PIL import Image

    pages: list[Image.Image] = []
    try:
        for image_path in images:
            img = _open_image(image_path)
            pages.append(img.convert("RGB"))
        first, rest = pages[0], pages[1:]
        first.save(
            out_path,
            "PDF",
            save_all=True,
            append_images=rest,
            resolution=float(_effective_dpi(first, cfg)),
        )
    finally:
        for img in pages:
            img.close()
    return ["" for _ in images]


# ---------------------------------------------------------------------------
# Buendeln
# ---------------------------------------------------------------------------

def bundle_workdir(bundle_id: str, cfg: Config) -> Path:
    return cfg.paths.temp_dir / BUNDLE_TEMP_DIRNAME / bundle_id


def load_bundle_meta(bundle_id: str, cfg: Config) -> dict | None:
    meta_path = bundle_workdir(bundle_id, cfg) / BUNDLE_META_FILENAME
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Bundle-Metadaten nicht lesbar (%s): %s", bundle_id, exc)
        return None


def bundle_page_images(bundle_id: str, cfg: Config) -> list[Path]:
    """Seitenbilder eines gebuendelten Scans in Seitenreihenfolge."""
    meta = load_bundle_meta(bundle_id, cfg)
    if not meta:
        return []
    workdir = bundle_workdir(bundle_id, cfg)
    paths = []
    for page in meta.get("pages", []):
        candidate = workdir / str(page.get("file", ""))
        if candidate.exists():
            paths.append(candidate)
    return paths


def cleanup_bundle(bundle_id: str, cfg: Config) -> None:
    """Loescht die temporaeren Seitenbilder eines Bundles."""
    workdir = bundle_workdir(bundle_id, cfg)
    if not workdir.exists():
        return
    if cfg.scan.keep_page_images_seconds > 0:
        logger.info(
            "Scan-Bundle %s: Seitenbilder bleiben laut Konfiguration erhalten (%s).",
            bundle_id,
            workdir,
        )
        return
    try:
        shutil.rmtree(workdir)
        logger.info("Scan-Bundle %s: temporaere Seitenbilder geloescht.", bundle_id)
    except OSError as exc:
        logger.warning("Scan-Bundle %s: Aufraeumen fehlgeschlagen: %s", bundle_id, exc)


def purge_stale_workdirs(cfg: Config) -> None:
    """Entfernt liegengebliebene Bundle-Ordner (z.B. nach Abbruch/Neustart)."""
    root = cfg.paths.temp_dir / BUNDLE_TEMP_DIRNAME
    if not root.exists():
        return
    max_age = max(cfg.scan.keep_page_images_seconds, 24 * 3600)
    now = time.time()
    for entry in root.iterdir():
        try:
            if entry.is_dir() and now - entry.stat().st_mtime > max_age:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


def finalize_bundle(bundle: ScanBundle, cfg: Config) -> Path | None:
    """Baut aus einem Bundle das PDF in der Inbox und raeumt die Einzelbilder weg."""
    if not bundle.pages:
        return None

    pages = bundle.pages[: max(1, cfg.scan.bundle_max_pages)]
    if len(bundle.pages) > len(pages):
        logger.warning(
            "Scan-Bundle %s: %d Seiten uebersteigen bundle_max_pages (%d) - Rest wird ignoriert.",
            bundle.bundle_id,
            len(bundle.pages),
            cfg.scan.bundle_max_pages,
        )

    workdir = bundle_workdir(bundle.bundle_id, cfg)
    workdir.mkdir(parents=True, exist_ok=True)

    staged: list[tuple[int, Path]] = []
    for position, (index, source_path) in enumerate(pages, start=1):
        target = workdir / f"page_{position:02d}{source_path.suffix.lower()}"
        try:
            shutil.move(str(source_path), str(target))
        except OSError as exc:
            logger.error("Scan-Bundle %s: Seite %s nicht verschiebbar: %s", bundle.bundle_id, source_path.name, exc)
            continue
        staged.append((index, target))

    if not staged:
        logger.error("Scan-Bundle %s: keine Seite konnte uebernommen werden.", bundle.bundle_id)
        return None

    title = sanitize_title(bundle.title, cfg)
    inbox = pages[0][1].parent
    pdf_path = inbox / f"{title}{TITLE_SEPARATOR}{bundle.bundle_id}.pdf"

    try:
        page_texts, has_text_layer = build_searchable_pdf([p for _, p in staged], pdf_path, cfg)
    except Exception as exc:
        logger.exception("Scan-Bundle %s: PDF-Erzeugung fehlgeschlagen.", bundle.bundle_id)
        _restore_pages(staged, inbox, bundle.bundle_id)
        raise RuntimeError(f"PDF-Erzeugung fehlgeschlagen: {exc}") from exc

    meta = {
        "bundle_id": bundle.bundle_id,
        "title": bundle.title or title,
        "source": bundle.source,
        "created_at": datetime.now().isoformat(),
        "pdf_filename": pdf_path.name,
        "page_count": len(staged),
        "has_text_layer": has_text_layer,
        "pages": [
            {
                "index": position,
                "original_index": index,
                "file": path.name,
                "ocr_text": page_texts[position - 1] if position - 1 < len(page_texts) else "",
            }
            for position, (index, path) in enumerate(staged, start=1)
        ],
    }
    (workdir / BUNDLE_META_FILENAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if bundle.manifest_path and bundle.manifest_path.exists():
        bundle.manifest_path.unlink(missing_ok=True)

    logger.info(
        "Scan-Bundle %s: %d Seite(n) -> %s (Textlayer: %s)",
        bundle.bundle_id,
        len(staged),
        pdf_path.name,
        "ja" if has_text_layer else "nein",
    )
    return pdf_path


def _restore_pages(staged: list[tuple[int, Path]], inbox: Path, bundle_id: str) -> None:
    """Schiebt Seiten nach einem Fehlschlag zurueck in die Inbox."""
    for index, path in staged:
        try:
            shutil.move(str(path), str(inbox / page_filename(bundle_id, index, path.suffix)))
        except OSError:
            logger.warning("Scan-Bundle %s: Seite %s konnte nicht zurueckgelegt werden.", bundle_id, path.name)


def finalize_ready_bundles(cfg: Config, only_bundle_id: str | None = None) -> list[Path]:
    """Buendelt alle fertigen Scans der Inbox und gibt die erzeugten PDF-Pfade zurueck."""
    if not cfg.scan.bundle_enabled:
        return []

    created: list[Path] = []
    for bundle in collect_bundles(cfg.paths.inbox):
        if only_bundle_id and bundle.bundle_id != only_bundle_id:
            continue
        if not is_ready(bundle, cfg):
            continue
        try:
            pdf_path = finalize_bundle(bundle, cfg)
        except Exception:
            continue
        if pdf_path:
            created.append(pdf_path)
    return created
