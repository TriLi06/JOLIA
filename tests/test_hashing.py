import tempfile
from pathlib import Path

from app.services.hashing_service import compute_sha256


def test_sha256_deterministic():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
        f.write(b"Testinhalt fuer SHA256")
        tmp = Path(f.name)

    h1 = compute_sha256(tmp)
    h2 = compute_sha256(tmp)
    assert h1 == h2
    assert len(h1) == 64
    tmp.unlink()


def test_sha256_different_content():
    with tempfile.NamedTemporaryFile(delete=False) as f1:
        f1.write(b"Inhalt A")
        p1 = Path(f1.name)
    with tempfile.NamedTemporaryFile(delete=False) as f2:
        f2.write(b"Inhalt B")
        p2 = Path(f2.name)

    assert compute_sha256(p1) != compute_sha256(p2)
    p1.unlink()
    p2.unlink()


def test_sha256_known_value():
    # SHA256 von b"hello" ist bekannt
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"hello")
        p = Path(f.name)

    result = compute_sha256(p)
    assert result == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    p.unlink()
