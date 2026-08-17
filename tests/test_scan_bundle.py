import json
import uuid
from pathlib import Path

import pytest

from app.config import (
    Config,
    ModelsConfig,
    PathsConfig,
    ProcessingConfig,
    ScanConfig,
    WatcherConfig,
)
from app.services import scan_bundle_service as sbs


def _make_config(tmp_path: Path, **scan_overrides) -> Config:
    inbox = tmp_path / "inbox"
    temp_dir = tmp_path / "temp"
    inbox.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    return Config(
        paths=PathsConfig(
            inbox=inbox,
            archive_root=tmp_path / "archive",
            data_dir=tmp_path / "data",
            temp_dir=temp_dir,
            backup_target=tmp_path / "backup",
        ),
        models=ModelsConfig(),
        processing=ProcessingConfig(),
        watcher=WatcherConfig(),
        scan=ScanConfig(**scan_overrides),
    )


def _write_image(path: Path, size=(600, 850), color=(255, 255, 255)) -> Path:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(img)
    draw.text((40, 40), "JOLIA Testseite", fill=(0, 0, 0))
    img.save(path, "JPEG", quality=90)
    return path


# ---------------------------------------------------------------------------
# Namenskonvention
# ---------------------------------------------------------------------------

def test_parse_page_name_accepts_uuid_with_and_without_dashes():
    plain = uuid.uuid4().hex
    dashed = str(uuid.uuid4())

    assert sbs.parse_page_name(Path(f"{plain}_01.jpg")) == (plain, 1)
    assert sbs.parse_page_name(Path(f"{dashed}_12.PNG")) == (dashed, 12)


def test_parse_page_name_ignores_regular_photos():
    assert sbs.parse_page_name(Path("IMG_20240101_01.jpg")) is None
    assert sbs.parse_page_name(Path("urlaub.jpg")) is None
    assert sbs.parse_page_name(Path(f"{uuid.uuid4().hex}_01.pdf")) is None


def test_bundle_id_from_pdf_name():
    bundle_id = uuid.uuid4().hex
    assert sbs.bundle_id_from_pdf_name(f"Rechnung_2026__{bundle_id}.pdf") == bundle_id
    assert sbs.bundle_id_from_pdf_name("Rechnung_2026.pdf") is None
    assert sbs.bundle_id_from_pdf_name("Rechnung__nicht-uuid.pdf") is None


def test_page_filename_pads_index():
    bundle_id = uuid.uuid4().hex
    assert sbs.page_filename(bundle_id, 3, "JPG") == f"{bundle_id}_03.jpg"


def test_sanitize_title_falls_back_to_prefix(tmp_path):
    cfg = _make_config(tmp_path, default_title_prefix="Scan")
    assert sbs.sanitize_title(None, cfg).startswith("Scan_")
    # Der Titel darf den Trenner nicht enthalten, sonst bricht bundle_id_from_pdf_name.
    assert sbs.TITLE_SEPARATOR not in sbs.sanitize_title("Rechnung__Stadtwerke", cfg)
    assert sbs.sanitize_title("Rechnung/Stadtwerke 2026", cfg) == "Rechnung_Stadtwerke 2026"


# ---------------------------------------------------------------------------
# Bundles einsammeln / Bereitschaft
# ---------------------------------------------------------------------------

def test_collect_bundles_groups_and_sorts_pages(tmp_path):
    cfg = _make_config(tmp_path)
    bundle_id = uuid.uuid4().hex
    other_id = uuid.uuid4().hex
    for index in (2, 1, 3):
        (cfg.paths.inbox / sbs.page_filename(bundle_id, index, ".jpg")).write_bytes(b"x")
    (cfg.paths.inbox / sbs.page_filename(other_id, 1, ".png")).write_bytes(b"x")
    (cfg.paths.inbox / "urlaub.jpg").write_bytes(b"x")

    bundles = {b.bundle_id: b for b in sbs.collect_bundles(cfg.paths.inbox)}

    assert set(bundles) == {bundle_id, other_id}
    assert [i for i, _ in bundles[bundle_id].pages] == [1, 2, 3]


def test_is_ready_requires_manifest_or_idle(tmp_path):
    cfg = _make_config(tmp_path, bundle_idle_seconds=3600)
    bundle_id = uuid.uuid4().hex
    (cfg.paths.inbox / sbs.page_filename(bundle_id, 1, ".jpg")).write_bytes(b"x")

    bundle = sbs.collect_bundles(cfg.paths.inbox)[0]
    assert sbs.is_ready(bundle, cfg) is False

    sbs.write_manifest(cfg.paths.inbox, bundle_id, complete=True)
    bundle = sbs.collect_bundles(cfg.paths.inbox)[0]
    assert sbs.is_ready(bundle, cfg) is True


def test_is_ready_waits_for_expected_pages(tmp_path):
    cfg = _make_config(tmp_path, bundle_idle_seconds=0)
    bundle_id = uuid.uuid4().hex
    (cfg.paths.inbox / sbs.page_filename(bundle_id, 1, ".jpg")).write_bytes(b"x")
    sbs.write_manifest(cfg.paths.inbox, bundle_id, complete=False, expected_pages=2)

    bundle = sbs.collect_bundles(cfg.paths.inbox)[0]
    assert sbs.is_ready(bundle, cfg) is False

    (cfg.paths.inbox / sbs.page_filename(bundle_id, 2, ".jpg")).write_bytes(b"x")
    bundle = sbs.collect_bundles(cfg.paths.inbox)[0]
    assert sbs.is_ready(bundle, cfg) is True


# ---------------------------------------------------------------------------
# PDF-Erzeugung
# ---------------------------------------------------------------------------

def test_build_image_only_pdf_without_textlayer(tmp_path):
    pytest.importorskip("PIL")
    from pypdf import PdfReader

    cfg = _make_config(tmp_path, pdf_ocr=False)
    images = [_write_image(tmp_path / f"page_{i}.jpg") for i in (1, 2)]
    out = tmp_path / "out.pdf"

    texts, has_layer = sbs.build_searchable_pdf(images, out, cfg)

    assert has_layer is False
    assert texts == ["", ""]
    assert len(PdfReader(str(out)).pages) == 2


def test_finalize_bundle_creates_pdf_and_moves_pages(tmp_path):
    pytest.importorskip("PIL")
    from pypdf import PdfReader

    cfg = _make_config(tmp_path, pdf_ocr=False)
    bundle_id = uuid.uuid4().hex
    for index in (1, 2):
        _write_image(cfg.paths.inbox / sbs.page_filename(bundle_id, index, ".jpg"))
    sbs.write_manifest(cfg.paths.inbox, bundle_id, title="Rechnung Test", complete=True)

    pdf_paths = sbs.finalize_ready_bundles(cfg)

    assert len(pdf_paths) == 1
    pdf_path = pdf_paths[0]
    assert pdf_path.name == f"Rechnung Test{sbs.TITLE_SEPARATOR}{bundle_id}.pdf"
    assert len(PdfReader(str(pdf_path)).pages) == 2
    assert sbs.bundle_id_from_pdf_name(pdf_path.name) == bundle_id

    # Seitenbilder und Manifest sind aus der Inbox verschwunden
    assert not list(cfg.paths.inbox.glob(f"{bundle_id}_*"))
    assert not sbs.manifest_path_for(cfg.paths.inbox, bundle_id).exists()

    # ... liegen aber fuer die Vision-Analyse im temp_dir bereit
    meta = sbs.load_bundle_meta(bundle_id, cfg)
    assert meta is not None
    assert meta["page_count"] == 2
    assert len(sbs.bundle_page_images(bundle_id, cfg)) == 2

    sbs.cleanup_bundle(bundle_id, cfg)
    assert sbs.load_bundle_meta(bundle_id, cfg) is None


def test_finalize_skips_bundles_that_are_not_ready(tmp_path):
    cfg = _make_config(tmp_path, bundle_idle_seconds=3600)
    bundle_id = uuid.uuid4().hex
    _write_image(cfg.paths.inbox / sbs.page_filename(bundle_id, 1, ".jpg"))

    assert sbs.finalize_ready_bundles(cfg) == []
    assert (cfg.paths.inbox / sbs.page_filename(bundle_id, 1, ".jpg")).exists()


def test_write_manifest_keeps_existing_values(tmp_path):
    cfg = _make_config(tmp_path)
    bundle_id = uuid.uuid4().hex

    sbs.write_manifest(cfg.paths.inbox, bundle_id, title="Vertrag", source="kotlin-app")
    path = sbs.write_manifest(cfg.paths.inbox, bundle_id, complete=True)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["title"] == "Vertrag"
    assert data["source"] == "kotlin-app"
    assert data["complete"] is True


# ---------------------------------------------------------------------------
# PdfProcessor-Anbindung
# ---------------------------------------------------------------------------

class _FakeFileRecord:
    def __init__(self, filename: str, size: int):
        self.id = uuid.uuid4().hex
        self.original_filename = filename
        self.sha256 = "0" * 64
        self.file_size = size


def test_pdf_processor_recognizes_scan_bundle(tmp_path):
    pytest.importorskip("PIL")
    from app.processors.pdf_processor import PdfProcessor

    cfg = _make_config(tmp_path, pdf_ocr=False, vision_per_page=False)
    bundle_id = uuid.uuid4().hex
    for index in (1, 2):
        _write_image(cfg.paths.inbox / sbs.page_filename(bundle_id, index, ".jpg"))
    sbs.write_manifest(cfg.paths.inbox, bundle_id, title="Vertrag", source="kotlin-app", complete=True)

    pdf_path = sbs.finalize_ready_bundles(cfg)[0]
    record = _FakeFileRecord(pdf_path.name, pdf_path.stat().st_size)

    result = PdfProcessor().process(pdf_path, record, cfg)

    assert result.success
    assert result.metadata["Quelle"] == "Scan (kotlin-app)"
    assert result.metadata["Durchsuchbarer Textlayer"] == "Nein"
    assert result.metadata["Seitenanzahl"] == 2
    # Seitenbilder werden nach der Verarbeitung entfernt
    assert sbs.load_bundle_meta(bundle_id, cfg) is None


def test_build_vision_chunks_separates_description_and_handwriting(tmp_path):
    from app.processors.pdf_processor import PdfProcessor

    cfg = _make_config(tmp_path)
    pages = [(1, "Rechnung Stadtwerke Betrag Gesamtsumme")]
    visions = [
        (1, "Das Bild zeigt ein gescanntes Formular mit Firmenlogo.", "Handschriftliche Notiz: bezahlt am Dienstag"),
        (2, "Das Bild zeigt eine leere Seite.", ""),
    ]

    chunks = PdfProcessor()._build_vision_chunks(visions, pages, cfg, next_index=5)

    assert [c.chunk_index for c in chunks] == [5, 6, 7]
    assert [c.chunk_type for c in chunks] == ["description", "ocr", "description"]
    assert [c.page for c in chunks] == [1, 1, 2]


def test_vision_text_already_in_textlayer_is_skipped(tmp_path):
    from app.processors.pdf_processor import PdfProcessor

    cfg = _make_config(tmp_path)
    page_text = "Rechnung Stadtwerke Musterstadt Gesamtbetrag zahlbar sofort"
    chunks = PdfProcessor()._build_vision_chunks(
        [(1, "", page_text)], [(1, page_text)], cfg, next_index=0
    )

    assert chunks == []
