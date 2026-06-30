"""
Phase E: Einfache Session-basierte Authentifizierung.

Konfiguration in config.yaml:
    app:
      auth_enabled: true
      auth_username: "admin"
      auth_password_hash: "<sha256 des Passworts>"
      auth_session_secret: "<zufälliger Secret>"

Passwort-Hash generieren:
    python -c "import hashlib; print(hashlib.sha256(b'meinPasswort').hexdigest())"
"""
from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

logger = logging.getLogger(__name__)
router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

# Pfade, die ohne Login erreichbar sind
_PUBLIC_PATHS = {"/auth/login", "/health", "/static"}


def is_authenticated(request: Request) -> bool:
    """Prüft ob die aktuelle Session authentifiziert ist."""
    from app.config import get_config
    cfg = get_config()
    if not cfg.app.auth_enabled:
        return True
    return request.session.get("authenticated") is True


def require_auth(request: Request):
    """FastAPI-Dependency: leitet zu /auth/login weiter wenn nicht eingeloggt."""
    if not is_authenticated(request):
        raise _redirect_to_login(request)


def _redirect_to_login(request: Request):
    """Gibt eine RedirectResponse zur Login-Seite zurück."""
    from fastapi import HTTPException
    # Wir werfen eine HTTPException mit redirect – wird in der Middleware abgefangen
    # Stattdessen: einfacher Mechanismus via Exception
    raise _LoginRequired(str(request.url))


class _LoginRequired(Exception):
    def __init__(self, redirect_to: str):
        self.redirect_to = redirect_to


@router.get("/auth/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request, error: str = ""):
    from app.config import get_config
    cfg = get_config()
    if not cfg.app.auth_enabled or is_authenticated(request):
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(
        request, "login.html", {"error": error, "app_name": cfg.app.app_name}
    )


@router.post("/auth/login", include_in_schema=False)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next_url: str = Form(default="/dashboard"),
):
    from app.config import get_config
    cfg = get_config()

    # Benutzername prüfen
    if username != cfg.app.auth_username:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Ungültiger Benutzername oder Passwort.", "app_name": cfg.app.app_name},
            status_code=401,
        )

    # Passwort prüfen (wenn Hash konfiguriert)
    if cfg.app.auth_password_hash:
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if password_hash != cfg.app.auth_password_hash:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Ungültiger Benutzername oder Passwort.", "app_name": cfg.app.app_name},
                status_code=401,
            )

    request.session["authenticated"] = True
    request.session["username"] = username
    logger.info("Benutzer '%s' hat sich eingeloggt.", username)

    # next_url-Sicherheitsprüfung: nur relative Pfade erlaubt
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/dashboard"

    return RedirectResponse(url=next_url, status_code=302)


@router.get("/auth/logout", include_in_schema=False)
def logout(request: Request):
    username = request.session.get("username", "?")
    request.session.clear()
    logger.info("Benutzer '%s' hat sich ausgeloggt.", username)
    return RedirectResponse(url="/auth/login", status_code=302)
