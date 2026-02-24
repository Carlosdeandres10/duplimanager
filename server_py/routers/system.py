import os
import uuid
import tempfile
import asyncio
import hashlib
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request
from server_py.utils.config_store import settings as settings_config
from server_py.utils.logger import get_log_files, read_log_file
from server_py.models.schemas import WasabiConnectionTest, WasabiSnapshotDetectRequest
from server_py.services.duplicacy import service as duplicacy_service
from server_py.core.helpers import (
    list_local_directory_items, test_wasabi_head_bucket, test_wasabi_write_bucket,
    build_wasabi_storage_url, build_wasabi_env, _remote_cache_key, _remote_cache_get, _remote_cache_set,
    scheduler_loop, scheduler_task
)


router = APIRouter(tags=["system"])

# ─── API ROUTES ───────────────────────────────────────────

@router.get("/api/health")
async def health():
    return {
        "ok": True,
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }


@router.get("/api/system/pick-folder")
def pick_folder(start: Optional[str] = None):
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo abrir el selector de carpetas: {exc}")

    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            initialdir=(start or os.getcwd()),
            title="Seleccionar carpeta",
            mustexist=False,
        )
        root.destroy()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error abriendo selector de carpetas: {exc}")

    if not selected:
        return {"ok": True, "cancelled": True}
    return {"ok": True, "path": selected}


@router.get("/api/system/list-local-items")
def list_local_items(root: str, relative: Optional[str] = ""):
    return list_local_directory_items(root_path=root, relative_path=relative or "")


@router.post("/api/system/test-wasabi")
def test_wasabi_connection(req: WasabiConnectionTest):
    return test_wasabi_head_bucket(
        endpoint=req.endpoint,
        region=req.region,
        bucket=req.bucket,
        access_id=req.accessId,
        access_key=req.accessKey,
    )


@router.post("/api/system/test-wasabi-write")
def test_wasabi_write(req: WasabiConnectionTest):
    return test_wasabi_write_bucket(
        endpoint=req.endpoint,
        region=req.region,
        bucket=req.bucket,
        access_id=req.accessId,
        access_key=req.accessKey,
    )


@router.post("/api/system/detect-wasabi-snapshots")
async def detect_wasabi_snapshots(req: WasabiSnapshotDetectRequest):
    storage_url = build_wasabi_storage_url(req.region, req.endpoint, req.bucket, req.directory)
    extra_env = build_wasabi_env(req.accessId, req.accessKey, "default")
    password = (req.password or "").strip() or None
    cache_key = _remote_cache_key(
        "wasabi-snapshots",
        storage_url,
        bool(password),
        hashlib.sha256((password or "").encode("utf-8")).hexdigest() if password else "",
    )
    cached = _remote_cache_get(cache_key)
    if cached is not None:
        return cached
    probe_snapshot_id = f"duplimanager-probe-{uuid.uuid4().hex[:8]}"

    with tempfile.TemporaryDirectory(prefix="duplimanager-wasabi-probe-") as tmp_dir:
        init_result = await duplicacy_service.init(
            tmp_dir,
            probe_snapshot_id,
            storage_url,
            password=password,
            encrypt=(True if password else False),
            extra_env=extra_env,
        )
        if init_result.get("code") != 0:
            detail = (init_result.get("stdout") or init_result.get("stderr") or "No se pudo acceder al storage de Duplicacy")
            if "likely to have been initialized with a password before" in detail:
                raise HTTPException(
                    status_code=400,
                    detail="Este storage de Duplicacy parece cifrado. Introduce la contraseña de Duplicacy y vuelve a detectar Snapshot IDs.",
                )
            if "password is not correct" in detail.lower() or "invalid password" in detail.lower():
                raise HTTPException(status_code=400, detail="La contraseña de Duplicacy no es correcta.")
            raise HTTPException(status_code=400, detail=detail)

        list_result = await duplicacy_service.list_snapshots(
            tmp_dir,
            password=password,
            storage_name="default",
            extra_env=extra_env,
            all_ids=True,
        )
        if list_result.get("code") != 0:
            detail = (list_result.get("stdout") or list_result.get("stderr") or "No se pudieron listar snapshots")
            raise HTTPException(status_code=400, detail=detail)

        snapshots = list_result.get("snapshots") or []
        grouped: Dict[str, Dict[str, Any]] = {}
        for s in snapshots:
            sid = str(s.get("id") or "").strip()
            if not sid:
                continue
            item = grouped.setdefault(sid, {"snapshotId": sid, "revisions": 0, "latestRevision": None, "latestCreatedAt": None})
            item["revisions"] += 1
            rev = s.get("revision")
            if item["latestRevision"] is None or (isinstance(rev, int) and rev > item["latestRevision"]):
                item["latestRevision"] = rev
                item["latestCreatedAt"] = s.get("createdAt")

        snapshot_ids = sorted(grouped.keys())
        payload = {
            "ok": True,
            "storageUrl": storage_url,
            "snapshotIds": snapshot_ids,
            "snapshots": [grouped[k] for k in snapshot_ids],
        }
        _remote_cache_set(cache_key, payload)
        return payload

# --- Config & Logs ---

@router.get("/api/config/settings")
async def get_settings():
    s = settings_config.read()
    if "duplicacyPath" not in s and "duplicacy_path" in s:
        s["duplicacyPath"] = s.get("duplicacy_path")
    return {"ok": True, "settings": s}

@router.put("/api/config/settings")
async def update_settings(req: Request):
    data = await req.json()
    if "duplicacyPath" in data and "duplicacy_path" not in data:
        data["duplicacy_path"] = data["duplicacyPath"]
    if "duplicacy_path" in data and "duplicacyPath" not in data:
        data["duplicacyPath"] = data["duplicacy_path"]
    current = settings_config.read()
    current.update(data)
    settings_config.write(current)
    return {"ok": True, "settings": current}

@router.get("/api/config/logs")
async def list_logs():
    return {"ok": True, "files": get_log_files()}

@router.get("/api/config/logs/{filename}")
async def read_log(filename: str):
    content = read_log_file(filename)
    if content is None:
        raise HTTPException(status_code=404, detail="Log file not found")
    return {"ok": True, "content": content}


@router.on_event("startup")
async def on_startup():
    global scheduler_task
    if scheduler_task is None or scheduler_task.done():
        scheduler_task = asyncio.create_task(scheduler_loop())


@router.on_event("shutdown")
async def on_shutdown():
    global scheduler_task
    if scheduler_task and not scheduler_task.done():
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
    scheduler_task = None

