import sys
import types
from pathlib import Path

from app.services import image_compression_service as compression


def test_compress_image_uses_required_denoising_and_avif_options(monkeypatch, tmp_path):
    calls = {}

    class FakeImage:
        info = {"exif": b"exif-data", "icc_profile": b"icc-data", "xmp": b"xmp-data"}
        width = 6000
        height = 3000
        size = (width, height)

        def __init__(self, size=None):
            self.size = size or (self.width, self.height)
            self.width, self.height = self.size

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def convert(self, _mode):
            return self

        def resize(self, size, resample):
            calls["resize"] = (size, resample)
            return FakeImage(size)

        def save(self, path, **kwargs):
            calls["png_save"] = kwargs
            Path(path).write_bytes(b"temporary-png")

    image_module = types.SimpleNamespace(
        open=lambda _path: FakeImage(),
        fromarray=lambda _pixels: FakeImage(),
        Resampling=types.SimpleNamespace(LANCZOS="lanczos"),
    )
    monkeypatch.setitem(sys.modules, "PIL", types.SimpleNamespace(Image=image_module))
    monkeypatch.setitem(sys.modules, "numpy", types.SimpleNamespace(asarray=lambda image: image))

    def cvt_color(pixels, _conversion):
        return pixels

    def denoise(pixels, _destination, **kwargs):
        calls["denoise"] = kwargs
        return pixels

    monkeypatch.setitem(
        sys.modules,
        "cv2",
        types.SimpleNamespace(
            COLOR_RGB2BGR="rgb-to-bgr",
            COLOR_BGR2RGB="bgr-to-rgb",
            cvtColor=cvt_color,
            fastNlMeansDenoisingColored=denoise,
        ),
    )
    monkeypatch.setattr(compression.os, "cpu_count", lambda: 16)

    def run_encoder(command, **kwargs):
        calls["command"] = command
        calls["run_kwargs"] = kwargs
        assert Path(command[command.index("--exif") + 1]).read_bytes() == b"exif-data"
        assert Path(command[command.index("--icc") + 1]).read_bytes() == b"icc-data"
        assert Path(command[command.index("--xmp") + 1]).read_bytes() == b"xmp-data"
        Path(command[-1]).write_bytes(b"encoded-avif")
        return types.SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(compression.subprocess, "run", run_encoder)
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"original-jpeg")
    output = tmp_path / "photo.avif"

    result = compression.compress_image(source, output)

    assert result.original_size == len(b"original-jpeg")
    assert result.compressed_size == len(b"encoded-avif")
    assert calls["denoise"] == {
        "h": 3,
        "hColor": 3,
        "templateWindowSize": 7,
        "searchWindowSize": 21,
    }
    assert calls["resize"] == ((4096, 2048), "lanczos")
    assert calls["png_save"] == {"format": "PNG", "icc_profile": b"icc-data"}
    assert calls["command"][:10] == [
        "avifenc",
        "--codec",
        "svt",
        "--speed",
        "0",
        "--jobs",
        "16",
        "--yuv",
        "420",
        "--advanced",
    ]
    assert calls["command"][10] == "crf=28"
    assert calls["run_kwargs"]["check"] is True
    assert output.read_bytes() == b"encoded-avif"


def test_compress_image_logs_encoder_warning_and_compression_summary(monkeypatch, tmp_path, caplog):
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"original")
    output = tmp_path / "photo.avif"

    def run_encoder(_command, **_kwargs):
        output.write_bytes(b"encoded")
        return types.SimpleNamespace(stdout="", stderr="WARNING: profile changed")

    monkeypatch.setattr(compression.subprocess, "run", run_encoder)
    monkeypatch.setitem(
        sys.modules,
        "PIL",
        types.SimpleNamespace(
            Image=types.SimpleNamespace(
                open=lambda _path: _SimpleImage(),
                fromarray=lambda _pixels: _SimpleImage(),
                Resampling=types.SimpleNamespace(LANCZOS="lanczos"),
            )
        ),
    )
    monkeypatch.setitem(sys.modules, "numpy", types.SimpleNamespace(asarray=lambda image: image))
    monkeypatch.setitem(
        sys.modules,
        "cv2",
        types.SimpleNamespace(
            COLOR_RGB2BGR="rgb-to-bgr",
            COLOR_BGR2RGB="bgr-to-rgb",
            cvtColor=lambda pixels, _conversion: pixels,
            fastNlMeansDenoisingColored=lambda pixels, _destination, **_kwargs: pixels,
        ),
    )

    with caplog.at_level("DEBUG", logger="app.services.image_compression_service"):
        compression.compress_image(source, output)

    assert "Bildkomprimierung gestartet" in caplog.text
    assert "AVIF-Encoder-Diagnose" in caplog.text
    assert "WARNING: profile changed" in caplog.text
    assert "Bildkomprimierung abgeschlossen" in caplog.text
    assert "Reduktion=" in caplog.text


def test_compress_image_logs_encoder_failure_output_and_reraises(monkeypatch, tmp_path, caplog):
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"original")

    def run_encoder(_command, **_kwargs):
        raise compression.subprocess.CalledProcessError(
            2,
            ["avifenc", "--codec", "svt"],
            output="encoder stdout",
            stderr="SVT codec unavailable",
        )

    monkeypatch.setattr(compression.subprocess, "run", run_encoder)
    monkeypatch.setitem(
        sys.modules,
        "PIL",
        types.SimpleNamespace(
            Image=types.SimpleNamespace(
                open=lambda _path: _SimpleImage(),
                fromarray=lambda _pixels: _SimpleImage(),
                Resampling=types.SimpleNamespace(LANCZOS="lanczos"),
            )
        ),
    )
    monkeypatch.setitem(sys.modules, "numpy", types.SimpleNamespace(asarray=lambda image: image))
    monkeypatch.setitem(
        sys.modules,
        "cv2",
        types.SimpleNamespace(
            COLOR_RGB2BGR="rgb-to-bgr",
            COLOR_BGR2RGB="bgr-to-rgb",
            cvtColor=lambda pixels, _conversion: pixels,
            fastNlMeansDenoisingColored=lambda pixels, _destination, **_kwargs: pixels,
        ),
    )

    with caplog.at_level("ERROR", logger="app.services.image_compression_service"):
        try:
            compression.compress_image(source, tmp_path / "photo.avif")
        except compression.subprocess.CalledProcessError:
            pass
        else:
            raise AssertionError("Encoder-Fehler wurde nicht weitergereicht.")

    assert "Bildkomprimierung fehlgeschlagen" in caplog.text
    assert "Exitcode=2" in caplog.text
    assert "encoder stdout" in caplog.text
    assert "SVT codec unavailable" in caplog.text


class _SimpleImage:
    info = {}
    size = (4, 4)
    width = 4
    height = 4

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def convert(self, _mode):
        return self

    def getexif(self):
        return {}

    def save(self, path, **_kwargs):
        Path(path).write_bytes(b"temporary-png")


def test_compress_directory_finds_supported_images_recursively(monkeypatch, tmp_path):
    (tmp_path / "top.jpg").write_bytes(b"jpg")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "inner.webp").write_bytes(b"webp")
    (nested / "ignored.bmp").write_bytes(b"bmp")
    submitted = {}

    class FakePool:
        def __init__(self, max_workers):
            submitted["max_workers"] = max_workers

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def map(self, _function, tasks):
            submitted["tasks"] = list(tasks)
            return ["done"] * len(submitted["tasks"])

    monkeypatch.setattr(compression, "ProcessPoolExecutor", FakePool)

    results = compression.compress_directory(tmp_path, max_workers=2)

    assert results == ["done", "done"]
    assert submitted["max_workers"] == 2
    assert [Path(task[0]).name for task in submitted["tasks"]] == ["inner.webp", "top.jpg"]
    assert [Path(task[1]).name for task in submitted["tasks"]] == ["inner.avif", "top.avif"]
