from typing import Any, List

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server_py.utils import config_store
from server_py.utils.logger import get_logger
from server_py.utils.paths import WEB_DIR, DOCS_DIR, DOCS_HTML_PATH
from server_py.services.panel_auth import is_panel_auth_enabled, is_session_valid, SESSION_COOKIE_NAME

# ─── CONFIG ───────────────────────────────────────────────
logger = get_logger("Server")
app = FastAPI(title="DupliManager API")


def _as_list_of_str(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x or "").strip() for x in value if str(x or "").strip()]
    if isinstance(value, str):
        raw = value.replace("\r", "\n")
        items: List[str] = []
        for chunk in raw.split("\n"):
            for piece in chunk.split(","):
                s = piece.strip()
                if s:
                    items.append(s)
        return items
    return []


def _configure_cors_from_settings() -> None:
    try:
        s = config_store.settings.read() or {}
        raw = dict(s.get("cors") or {})
        enabled = bool(raw.get("enabled", False))
        if not enabled:
            logger.info("[CORS] Deshabilitado (same-origin recomendado por defecto)")
            return

        requested_origins = _as_list_of_str(raw.get("allowOrigins"))
        allow_origins: List[str] = []
        dropped_wildcard = False
        for origin in requested_origins:
            if origin == "*":
                dropped_wildcard = True
                continue
            allow_origins.append(origin)
        if dropped_wildcard:
            logger.warning("[CORS] Se ignoró '*' en allowOrigins. Usa orígenes explícitos.")
        if not allow_origins:
            logger.warning("[CORS] enabled=true pero no hay orígenes válidos; CORS queda deshabilitado")
            return

        allow_methods = _as_list_of_str(raw.get("allowMethods")) or ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
        allow_headers = _as_list_of_str(raw.get("allowHeaders")) or ["*"]
        allow_credentials = bool(raw.get("allowCredentials", False))

        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_methods=allow_methods,
            allow_headers=allow_headers,
            allow_credentials=allow_credentials,
        )
        logger.info(
            "[CORS] Habilitado origins=%s credentials=%s",
            len(allow_origins),
            allow_credentials,
        )
    except Exception:
        logger.exception("[CORS] Error aplicando configuración CORS")


_configure_cors_from_settings()


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path or "/"
    # Static assets y shell HTML siempre accesibles; la UI se bloquea con overlay.
    if not path.startswith("/api/"):
        return await call_next(request)

    # Rutas API públicas/minimas
    public_api_prefixes = {
        "/api/health",
        "/api/auth/status",
        "/api/auth/login",
        "/api/auth/logout",
    }
    if any(path.startswith(p) for p in public_api_prefixes):
        return await call_next(request)

    if is_panel_auth_enabled():
        token = request.cookies.get(SESSION_COOKIE_NAME)
        if not is_session_valid(token):
            return JSONResponse(status_code=401, content={"ok": False, "detail": "Acceso al panel bloqueado. Inicia sesión."})

    return await call_next(request)

# ─── ROUTERS ────────────────────────────────────────────────
from server_py.routers import storages, backups, restore, system

app.include_router(storages.router)
app.include_router(backups.router)
app.include_router(restore.router)
app.include_router(system.router)

# --- Frontend Serving ---
app.mount("/css", StaticFiles(directory=str(WEB_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(WEB_DIR / "js")), name="js")
if DOCS_DIR.exists():
    app.mount("/docs", StaticFiles(directory=str(DOCS_DIR)), name="docs")


@app.get("/docs.html")
async def serve_docs_html():
    if not DOCS_HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="Manual no disponible en esta instalación")
    return FileResponse(str(DOCS_HTML_PATH))

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")
    # Fallback to index.html for SPA routing
    return FileResponse(str(WEB_DIR / "index.html"))

if __name__ == "__main__":
    settings_data = config_store.settings.read()
    port = settings_data.get("port", 8500)
    host = str(settings_data.get("host") or "127.0.0.1").strip() or "127.0.0.1"
    logger.info(f"🚀 DupliManager (Python) iniciando en http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
