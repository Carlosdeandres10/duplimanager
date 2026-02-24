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

# ─── CONFIG ───────────────────────────────────────────────
logger = get_logger("Server")
app = FastAPI(title="DupliManager API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    logger.info(f"🚀 DupliManager (Python) iniciando en http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
