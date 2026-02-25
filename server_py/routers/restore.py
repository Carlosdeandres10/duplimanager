import os
import signal
import time
import hashlib
import asyncio
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from server_py.utils.config_store import repositories as repositories_config
from server_py.models.schemas import RestoreRequest, RestoreCancelRequest
from server_py.services.duplicacy import service as duplicacy_service
from server_py.core.helpers import (
    get_primary_storage, get_storage_env, describe_storage,
    summarize_path_selection, ensure_restore_target_initialized,
    _remote_cache_key, _remote_cache_get, _remote_cache_set, 
    get_repo_duplicacy_password,
    FIXED_DUPLICACY_THREADS, logger, config_store
)

router = APIRouter(tags=["restore"])
active_restore_processes: Dict[str, Any] = {}
active_restore_cancel_flags: Dict[str, bool] = {}
active_restores: Dict[str, Dict[str, Any]] = {}
completed_restores: Dict[str, Dict[str, Any]] = {}


def _terminate_restore_process(proc: Any) -> None:
    try:
        proc.terminate()
        return
    except Exception:
        pass
    try:
        pid = getattr(proc, "pid", None)
        if pid:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass

# --- Snapshots & Restore ---

@router.get("/api/snapshots/{repo_id}")
async def list_snapshots(
    repo_id: str,
    password: Optional[str] = None,
    storage: Optional[str] = None,
    refresh: bool = False,
):
    repos_data = config_store.repositories.read()
    repo_ids = [r.get("id") for r in repos_data]
    logger.info(f"[Snapshots] Solicitando {repo_id} | IDs en BD: {repo_ids}")
    
    repo = next((r for r in repos_data if r["id"] == repo_id), None)
    if not repo:
        logger.warning(f"[Snapshots] No se encuentra {repo_id} en la lista {repo_ids}")
        raise HTTPException(status_code=404, detail=f"Repository not found: {repo_id}")

    storage_name = storage or (get_primary_storage(repo) or {}).get("name")
    
    # Auto-recuperar password si no viene en la request
    effective_password = password or get_repo_duplicacy_password(repo, storage_name)
    
    # Cache key for snapshots
    cache_key = _remote_cache_key(
        "repo-snapshots",
        repo_id,
        storage_name,
        bool(effective_password),
        hashlib.sha256((effective_password or "").encode("utf-8")).hexdigest() if effective_password else "",
    )
    cached = None if refresh else _remote_cache_get(cache_key)
    if cached is not None:
        return cached

    result = await duplicacy_service.list_snapshots(
        repo["path"],
        password=effective_password,
        storage_name=storage_name,
        extra_env=get_storage_env(repo, storage_name)
    )
    
    if result["code"] != 0:
        raise HTTPException(status_code=500, detail=result.get("stdout") or result.get("stderr") or "No se pudieron listar snapshots")
    
    payload = {"ok": True, "snapshots": result["snapshots"]}
    _remote_cache_set(cache_key, payload)
    return payload


@router.get("/api/snapshots/{repo_id}/files")
async def list_snapshot_files(repo_id: str, revision: int, password: Optional[str] = None, storage: Optional[str] = None):
    repos_data = config_store.repositories.read()
    repo = next((r for r in repos_data if r["id"] == repo_id), None)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    storage_name = storage or (get_primary_storage(repo) or {}).get("name")
    
    # Auto-recuperar password
    effective_password = password or get_repo_duplicacy_password(repo, storage_name)
    
    # Cache key for files
    cache_key = _remote_cache_key(
        "repo-files",
        repo_id,
        storage_name,
        revision,
        bool(effective_password),
        hashlib.sha256((effective_password or "").encode("utf-8")).hexdigest() if effective_password else "",
    )
    cached = _remote_cache_get(cache_key)
    if cached is not None:
        return cached

    result = await duplicacy_service.list_files(
        repo["path"],
        revision=revision,
        password=effective_password,
        storage_name=storage_name,
        extra_env=get_storage_env(repo, storage_name),
    )
    if result["code"] != 0:
        raise HTTPException(status_code=500, detail=result.get("stdout") or result.get("stderr") or "No se pudo listar archivos")
    
    payload = {"ok": True, "files": result["files"]}
    _remote_cache_set(cache_key, payload)
    return payload

@router.post("/api/restore")
async def restore(req: RestoreRequest):
    repos_data = config_store.repositories.read()
    repo = next((r for r in repos_data if r["id"] == req.repoId), None)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if req.repoId in active_restores:
        raise HTTPException(status_code=409, detail="Ya hay una restauración en ejecución para ese backup")

    started_monotonic = time.monotonic()
    storage_name = req.storageName or (get_primary_storage(repo) or {}).get("name")
    restore_path = (req.restorePath or "").strip()
    working_path = repo["path"]
    logger.info(
        "[Restore] Inicio repo=%s nombre=%s revision=%s origen=%s destino=%s storage=%s overwrite=%s threads=%s seleccion=%s",
        req.repoId,
        repo.get("name", "—"),
        req.revision,
        repo.get("path", "—"),
        restore_path or repo.get("path", "—"),
        describe_storage(repo, storage_name),
        bool(req.overwrite),
        FIXED_DUPLICACY_THREADS,
        summarize_path_selection(req.patterns),
    )
    # Auto-recuperar password
    effective_password = req.password or get_repo_duplicacy_password(repo, storage_name)

    active_restores[req.repoId] = {
        "status": "running",
        "startedAt": datetime.now().isoformat(),
        "lastOutput": "Iniciando restauración...",
        "outputLines": [],
        "cancelRequested": False,
        "revision": req.revision,
        "restorePath": restore_path or repo.get("path"),
    }
    active_restore_cancel_flags[req.repoId] = False
    completed_restores.pop(req.repoId, None)

    async def run_restore_task():
        result: Dict[str, Any] = {"code": -1, "stdout": "", "stderr": "Error no especificado"}
        local_working_path = working_path
        started_task_monotonic = time.monotonic()

        def on_progress(text: str):
            if req.repoId in active_restores:
                clean = (text or "").rstrip("\r\n")
                if clean:
                    active_restores[req.repoId]["lastOutput"] = clean
                    active_restores[req.repoId].setdefault("outputLines", []).append(clean)

        def on_process_start(proc: Any):
            active_restore_processes[req.repoId] = proc
            if req.repoId in active_restores:
                active_restores[req.repoId]["pid"] = getattr(proc, "pid", None)

        try:
            if restore_path and os.path.normcase(os.path.abspath(restore_path)) != os.path.normcase(os.path.abspath(repo["path"])):
                await ensure_restore_target_initialized(repo, restore_path, effective_password, storage_name)
                local_working_path = restore_path

            result = await duplicacy_service.restore(
                local_working_path,
                req.revision,
                overwrite=req.overwrite,
                password=effective_password,
                storage_name=storage_name,
                extra_env=get_storage_env(repo, storage_name),
                patterns=req.patterns or None,
                threads=FIXED_DUPLICACY_THREADS,
                on_progress=on_progress,
                on_process_start=on_process_start,
            )

            duration = round(time.monotonic() - started_task_monotonic, 2)
            was_cancelled = bool((active_restores.get(req.repoId) or {}).get("cancelRequested")) or bool(active_restore_cancel_flags.get(req.repoId))
            if result.get("code") != 0 and not was_cancelled:
                logger.error(
                    "[Restore] Fin repo=%s nombre=%s revision=%s resultado=ERROR codigo=%s duracion_s=%s",
                    req.repoId,
                    repo.get("name", "—"),
                    req.revision,
                    result.get("code"),
                    duration,
                )
            else:
                logger.info(
                    "[Restore] Fin repo=%s nombre=%s revision=%s resultado=%s codigo=%s duracion_s=%s destino_real=%s",
                    req.repoId,
                    repo.get("name", "—"),
                    req.revision,
                    "CANCELLED" if was_cancelled else "OK",
                    result.get("code"),
                    duration,
                    local_working_path,
                )

            completed_restores[req.repoId] = {
                "done": True,
                "code": result.get("code", -1),
                "stdout": result.get("stdout", "") or "",
                "stderr": result.get("stderr", "") or "",
                "finishedAt": datetime.now().isoformat(),
                "canceled": was_cancelled,
                "restorePath": local_working_path,
            }
        except Exception as exc:
            duration = round(time.monotonic() - started_task_monotonic, 2)
            logger.exception(
                "[Restore] Excepción inesperada repo=%s nombre=%s revision=%s duracion_s=%s",
                req.repoId,
                repo.get("name", "—"),
                req.revision,
                duration,
            )
            completed_restores[req.repoId] = {
                "done": True,
                "code": result.get("code", -1),
                "stdout": result.get("stdout", "") or "",
                "stderr": str(exc),
                "finishedAt": datetime.now().isoformat(),
                "canceled": bool((active_restores.get(req.repoId) or {}).get("cancelRequested")) or bool(active_restore_cancel_flags.get(req.repoId)),
                "restorePath": local_working_path,
            }
        finally:
            active_restore_processes.pop(req.repoId, None)
            active_restore_cancel_flags.pop(req.repoId, None)
            active_restores.pop(req.repoId, None)

    asyncio.create_task(run_restore_task())
    return {"ok": True}


@router.post("/api/restore/cancel")
async def cancel_restore(req: RestoreCancelRequest):
    info = active_restores.get(req.repoId)
    if not info:
        raise HTTPException(status_code=404, detail="No hay restauración en ejecución para ese backup")
    info["cancelRequested"] = True
    info["lastOutput"] = "Cancelación solicitada por el usuario..."
    info.setdefault("outputLines", []).append("⏹ Cancelación solicitada por el usuario...")
    proc = active_restore_processes.get(req.repoId)
    if not proc:
        raise HTTPException(status_code=409, detail="No se encontró el proceso de restauración en ejecución")
    active_restore_cancel_flags[req.repoId] = True
    _terminate_restore_process(proc)
    logger.warning("[Restore] Cancelación solicitada repo=%s", req.repoId)
    return {"ok": True, "message": "Cancelación de restauración solicitada"}


@router.get("/api/restore/progress/{repo_id}")
async def restore_progress(repo_id: str):
    async def event_generator():
        sent_lines = 0
        while True:
            info = active_restores.get(repo_id)
            if info:
                lines = info.get("outputLines") or []
                if sent_lines < len(lines):
                    chunk = "\n".join(lines[sent_lines:])
                    sent_lines = len(lines)
                    yield f"data: {json.dumps({'running': True, 'output': chunk})}\n\n"
                else:
                    yield f"data: {json.dumps({'running': True})}\n\n"
                await asyncio.sleep(1)
                continue

            completed = completed_restores.pop(repo_id, None)
            if completed:
                payload = {
                    "done": True,
                    "success": completed.get("code", -1) == 0 and not completed.get("canceled"),
                    "canceled": bool(completed.get("canceled")),
                    "code": completed.get("code", -1),
                    "finalOutput": completed.get("stdout", "") or completed.get("stderr", ""),
                    "restorePath": completed.get("restorePath"),
                }
                yield f"data: {json.dumps(payload)}\n\n"
                break

            yield f"data: {json.dumps({'done': True})}\n\n"
            await asyncio.sleep(1)
            break

    return StreamingResponse(event_generator(), media_type="text/event-stream")
