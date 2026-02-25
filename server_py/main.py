import os
import uuid
import asyncio
import hashlib
import hmac
import time
import signal
import tempfile
import json
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from pathlib import Path
from urllib import request as urllib_request, error as urllib_error
from urllib.parse import quote
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from server_py.utils.logger import get_logger, get_log_files, read_log_file
from server_py.utils import config_store
from server_py.services.duplicacy import service as duplicacy_service
from server_py.services.panel_auth import is_panel_auth_enabled, is_session_valid, SESSION_COOKIE_NAME

# ─── CONFIG ───────────────────────────────────────────────
logger = get_logger("Server")
app = FastAPI(title="DupliManager API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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

# ─── MODELS ───────────────────────────────────────────────
from server_py.models.schemas import (
    RepoCreate, BackupStart, BackupCancelRequest, RestoreRequest, StorageRestoreRequest,
    WasabiConnectionTest, WasabiSnapshotDetectRequest, RepoUpdate, StorageCreate, StorageUpdate
)
# ─── ROUTERS ────────────────────────────────────────────────
from server_py.routers import storages, backups, restore, system

app.include_router(storages.router)
app.include_router(backups.router)
app.include_router(restore.router)
app.include_router(system.router)

# --- Frontend Serving ---
ROOT_DIR = Path(__file__).parent.parent
WEB_DIR = ROOT_DIR / "web"

app.mount("/css", StaticFiles(directory=str(WEB_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(WEB_DIR / "js")), name="js")

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")
    # Fallback to index.html for SPA routing
    return FileResponse(str(WEB_DIR / "index.html"))

# ─── MAIN ─────────────────────────────────────────────────
import uvicorn
import json

if __name__ == "__main__":
    settings_data = config_store.settings.read()
    port = settings_data.get("port", 8500)
    host = str(settings_data.get("host") or "127.0.0.1").strip() or "127.0.0.1"
    logger.info(f"🚀 DupliManager (Python) iniciando en http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
