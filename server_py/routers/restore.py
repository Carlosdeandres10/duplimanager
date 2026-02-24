import os
import time
import hashlib
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException
from server_py.utils.config_store import repositories as repositories_config
from server_py.models.schemas import RestoreRequest
from server_py.services.duplicacy import service as duplicacy_service
from server_py.core.helpers import (
    get_primary_storage, get_storage_env, describe_storage,
    summarize_path_selection, ensure_restore_target_initialized,
    _remote_cache_key, _remote_cache_get, _remote_cache_set, 
    get_repo_duplicacy_password,
    FIXED_DUPLICACY_THREADS, logger, config_store
)

router = APIRouter(tags=["restore"])

# --- Snapshots & Restore ---

@router.get("/api/snapshots/{repo_id}")
async def list_snapshots(repo_id: str, password: Optional[str] = None, storage: Optional[str] = None):
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
    cached = _remote_cache_get(cache_key)
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

    if restore_path and os.path.normcase(os.path.abspath(restore_path)) != os.path.normcase(os.path.abspath(repo["path"])):
        await ensure_restore_target_initialized(repo, restore_path, effective_password, storage_name)
        working_path = restore_path

    result = await duplicacy_service.restore(
        working_path, 
        req.revision, 
        overwrite=req.overwrite, 
        password=effective_password,
        storage_name=storage_name,
        extra_env=get_storage_env(repo, storage_name),
        patterns=req.patterns or None,
        threads=FIXED_DUPLICACY_THREADS,
    )
    
    if result["code"] != 0:
        duration = round(time.monotonic() - started_monotonic, 2)
        logger.error(
            "[Restore] Fin repo=%s nombre=%s revision=%s resultado=ERROR codigo=%s duracion_s=%s",
            req.repoId,
            repo.get("name", "—"),
            req.revision,
            result.get("code"),
            duration,
        )
        raise HTTPException(status_code=500, detail=result.get("stdout") or result.get("stderr") or "Restore failed")

    duration = round(time.monotonic() - started_monotonic, 2)
    logger.info(
        "[Restore] Fin repo=%s nombre=%s revision=%s resultado=OK codigo=%s duracion_s=%s destino_real=%s",
        req.repoId,
        repo.get("name", "—"),
        req.revision,
        duration,
        working_path,
    )
    return {"ok": True, "output": result["stdout"], "restorePath": working_path}
