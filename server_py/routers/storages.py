from typing import List, Optional, Dict, Any
import os
import signal
import asyncio
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import uuid
import time
import hashlib
from datetime import datetime
from server_py.utils.config_store import storages as storages_config
from server_py.models.schemas import (
    StorageCreate,
    StorageUpdate,
    StorageRestoreRequest,
    StorageRestoreCancelRequest,
    WasabiSnapshotDetectRequest,
)
from server_py.services.duplicacy import service as duplicacy_service
from server_py.utils.secret_crypto import protect_secrets_deep, reveal_secret
from server_py.core.helpers import (
    sanitize_storage, list_all_storages_for_ui, test_wasabi_head_bucket, 
    validate_wasabi_duplicacy_storage_access_if_initialized, build_wasabi_storage_url,
    get_storage_by_id, _remote_cache_key, _remote_cache_get, _remote_cache_set,
    with_temp_storage_session_list_snapshots, with_temp_storage_session_list_files,
    ensure_restore_target_initialized_from_storage, get_storage_record_env, FIXED_DUPLICACY_THREADS,
    summarize_path_selection, do_detect_wasabi_snapshots, logger
)

router = APIRouter(tags=["storages"])
active_storage_restore_processes: Dict[str, Any] = {}
active_storage_restore_cancel_flags: Dict[str, bool] = {}
active_storage_restores: Dict[str, Dict[str, Any]] = {}
completed_storage_restores: Dict[str, Dict[str, Any]] = {}


def _terminate_storage_restore_process(proc: Any) -> None:
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

# --- Storages ---

@router.get("/api/storages")
async def get_storages():
    return {"ok": True, "storages": [sanitize_storage(s) for s in list_all_storages_for_ui()]}


@router.post("/api/storages")
async def create_storage(req: StorageCreate):
    storage_type = (req.type or "").strip().lower()
    if storage_type not in {"local", "wasabi"}:
        raise HTTPException(status_code=400, detail="type debe ser 'local' o 'wasabi'")

    storages = storages_config.read()
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="El nombre del storage es obligatorio")

    if storage_type == "local":
        local_path = (req.localPath or "").strip()
        if not local_path:
            raise HTTPException(status_code=400, detail="Falta la ruta del storage local")
        url = local_path
        record = {
            "id": str(uuid.uuid4()),
            "name": name,
            "label": name,
            "type": "local",
            "url": url,
            "localPath": local_path,
            "createdAt": datetime.now().isoformat(),
            "source": "managed",
        }
    else:
        endpoint = (req.endpoint or "").strip()
        region = (req.region or "").strip()
        bucket = (req.bucket or "").strip()
        directory = (req.directory or "").strip()
        access_id = (req.accessId or "").strip()
        access_key = (req.accessKey or "").strip()
        if not all([endpoint, region, bucket, access_id, access_key]):
            raise HTTPException(status_code=400, detail="Faltan campos de Wasabi para importar el storage")

        # Validación básica de acceso al bucket
        test_wasabi_head_bucket(endpoint, region, bucket, access_id, access_key)
        dup_pwd = (req.duplicacyPassword or "").strip()
        validation = await validate_wasabi_duplicacy_storage_access_if_initialized(
            endpoint=endpoint,
            region=region,
            bucket=bucket,
            directory=directory,
            access_id=access_id,
            access_key=access_key,
            duplicacy_password=dup_pwd or None,
        )
        url = build_wasabi_storage_url(region, endpoint, bucket, directory)
        record = {
            "id": str(uuid.uuid4()),
            "name": name,
            "label": name,
            "type": "wasabi",
            "url": url,
            "endpoint": endpoint,
            "region": region,
            "bucket": bucket,
            "directory": directory,
            "createdAt": datetime.now().isoformat(),
            "source": "managed",
            "_secrets": {
                "accessId": access_id,
                "accessKey": access_key,
            }
        }
        if dup_pwd:
            record["_secrets"]["duplicacyPassword"] = req.duplicacyPassword
        record["_secrets"] = protect_secrets_deep(record.get("_secrets") or {})

    # Deduplicado simple por URL + tipo (actualiza alias/secretos si ya existe)
    existing = next((s for s in storages if s.get("type") == record.get("type") and (s.get("url") or s.get("localPath")) == (record.get("url") or record.get("localPath"))), None)
    if existing:
        existing["name"] = record["name"]
        existing["label"] = record["label"]
        if record.get("_secrets"):
            record["_secrets"] = protect_secrets_deep(record.get("_secrets") or {})
            existing.setdefault("_secrets", {}).update(record["_secrets"])
        if storage_type == "wasabi":
            for key in ("endpoint", "region", "bucket", "directory", "url"):
                existing[key] = record.get(key)
        else:
            existing["localPath"] = record.get("localPath")
            existing["url"] = record.get("url")
        storages_config.write(storages)
        response = {"ok": True, "storage": sanitize_storage(existing), "updated": True}
        if storage_type == "wasabi" and 'validation' in locals() and not validation.get("checked"):
            response["warning"] = validation.get("message")
        return response

    storages.append(record)
    storages_config.write(storages)
    response = {"ok": True, "storage": sanitize_storage(record)}
    if storage_type == "wasabi" and 'validation' in locals() and not validation.get("checked"):
        response["warning"] = validation.get("message")
    return response


@router.put("/api/storages/{storage_id}")
async def update_storage(storage_id: str, req: StorageUpdate):
    storages = storages_config.read()
    target = next((s for s in storages if s.get("id") == storage_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Storage no encontrado")
    if (target.get("source") or "managed") != "managed":
        raise HTTPException(status_code=400, detail="Los storages derivados (legacy) no se editan desde esta vista")

    storage_type = (target.get("type") or "").strip().lower()
    new_name = (req.name or "").strip()
    if new_name:
        target["name"] = new_name
        target["label"] = new_name

    if storage_type == "local":
        if req.localPath is not None:
            new_local_path = (req.localPath or "").strip()
            if not new_local_path:
                raise HTTPException(status_code=400, detail="La ruta del storage local no puede estar vacía")
            target["localPath"] = new_local_path
            target["url"] = new_local_path
        storages_config.write(storages)
        return {"ok": True, "storage": sanitize_storage(target)}

    if storage_type != "wasabi":
        raise HTTPException(status_code=400, detail="Tipo de storage no soportado para edición")

    # Wasabi fields (blank => keep current)
    endpoint = (req.endpoint or "").strip() if req.endpoint is not None else (target.get("endpoint") or "")
    region = (req.region or "").strip() if req.region is not None else (target.get("region") or "")
    bucket = (req.bucket or "").strip() if req.bucket is not None else (target.get("bucket") or "")
    directory = (req.directory or "").strip() if req.directory is not None else (target.get("directory") or "")
    secrets = target.setdefault("_secrets", {})
    access_id = (req.accessId or "").strip() if req.accessId is not None and (req.accessId or "").strip() else (reveal_secret(secrets.get("accessId")) or "")
    access_key = (req.accessKey or "").strip() if req.accessKey is not None and (req.accessKey or "").strip() else (reveal_secret(secrets.get("accessKey")) or "")

    if not all([endpoint, region, bucket, access_id, access_key]):
        raise HTTPException(status_code=400, detail="Faltan datos de Wasabi (endpoint, región, bucket o credenciales)")

    # Validate access with resulting values
    test_wasabi_head_bucket(endpoint, region, bucket, access_id, access_key)
    effective_dup_pwd = None
    if req.clearDuplicacyPassword:
        effective_dup_pwd = None
    elif req.duplicacyPassword is not None and (req.duplicacyPassword or "").strip():
        effective_dup_pwd = req.duplicacyPassword
    else:
        effective_dup_pwd = (reveal_secret(secrets.get("duplicacyPassword")) or None)
    validation = await validate_wasabi_duplicacy_storage_access_if_initialized(
        endpoint=endpoint,
        region=region,
        bucket=bucket,
        directory=directory,
        access_id=access_id,
        access_key=access_key,
        duplicacy_password=effective_dup_pwd,
    )

    target["endpoint"] = endpoint
    target["region"] = region
    target["bucket"] = bucket
    target["directory"] = directory
    target["url"] = build_wasabi_storage_url(region, endpoint, bucket, directory)
    secrets["accessId"] = access_id
    secrets["accessKey"] = access_key

    if req.duplicacyPassword is not None:
        # blank means "keep current"; use clearDuplicacyPassword to remove explicitly
        if (req.duplicacyPassword or "").strip():
            secrets["duplicacyPassword"] = req.duplicacyPassword
    if req.clearDuplicacyPassword:
        secrets.pop("duplicacyPassword", None)
    target["_secrets"] = protect_secrets_deep(secrets)

    storages_config.write(storages)
    response = {"ok": True, "storage": sanitize_storage(target)}
    if not validation.get("checked"):
        response["warning"] = validation.get("message")
    return response


@router.delete("/api/storages/{storage_id}")
async def delete_storage(storage_id: str):
    storages = storages_config.read()
    target = next((s for s in storages if s.get("id") == storage_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Storage no encontrado")
    storages = [s for s in storages if s.get("id") != storage_id]
    storages_config.write(storages)
    return {"ok": True, "removed": sanitize_storage(target)}


@router.get("/api/storages/{storage_id}/snapshots")
async def detect_storage_snapshots(storage_id: str):
    storage = get_storage_by_id(storage_id)
    if not storage:
        raise HTTPException(status_code=404, detail="Storage no encontrado")
    if (storage.get("type") or "").lower() != "wasabi":
        raise HTTPException(status_code=400, detail="La detección de Snapshot IDs está disponible en Wasabi (MVP)")

    req = WasabiSnapshotDetectRequest(
        endpoint=storage.get("endpoint") or "",
        region=storage.get("region") or "",
        bucket=storage.get("bucket") or "",
        directory=storage.get("directory") or "",
        accessId=(reveal_secret((storage.get("_secrets") or {}).get("accessId")) or ""),
        accessKey=(reveal_secret((storage.get("_secrets") or {}).get("accessKey")) or ""),
        password=(reveal_secret((storage.get("_secrets") or {}).get("duplicacyPassword")) or None),
    )
    return await do_detect_wasabi_snapshots(req)


@router.get("/api/storages/{storage_id}/snapshot-revisions")
async def list_storage_snapshot_revisions(
    storage_id: str,
    snapshot_id: str,
    password: Optional[str] = None,
    refresh: bool = False,
):
    storage = get_storage_by_id(storage_id)
    if not storage:
        raise HTTPException(status_code=404, detail="Storage no encontrado")
    snapshot_id = (snapshot_id or "").strip()
    if not snapshot_id:
        raise HTTPException(status_code=400, detail="snapshot_id es obligatorio")
    effective_password = (password or "").strip() or (reveal_secret((storage.get("_secrets") or {}).get("duplicacyPassword")) or None)
    cache_key = _remote_cache_key(
        "storage-revisions",
        storage_id,
        snapshot_id,
        bool(effective_password),
        hashlib.sha256((effective_password or "").encode("utf-8")).hexdigest() if effective_password else "",
    )
    cached = None if refresh else _remote_cache_get(cache_key)
    if cached is not None:
        return cached
    result = await with_temp_storage_session_list_snapshots(
        storage=storage,
        snapshot_id=snapshot_id,
        password=effective_password,
    )
    if result.get("code") != 0:
        raise HTTPException(status_code=500, detail=result.get("stdout") or result.get("stderr") or "No se pudieron listar revisiones")
    snapshots = [s for s in (result.get("snapshots") or []) if str(s.get("id") or "") == snapshot_id]
    payload = {"ok": True, "snapshots": snapshots}
    _remote_cache_set(cache_key, payload)
    return payload


@router.get("/api/storages/{storage_id}/snapshot-files")
async def list_storage_snapshot_files(storage_id: str, snapshot_id: str, revision: int, password: Optional[str] = None):
    storage = get_storage_by_id(storage_id)
    if not storage:
        raise HTTPException(status_code=404, detail="Storage no encontrado")
    snapshot_id = (snapshot_id or "").strip()
    if not snapshot_id:
        raise HTTPException(status_code=400, detail="snapshot_id es obligatorio")
    effective_password = (password or "").strip() or (reveal_secret((storage.get("_secrets") or {}).get("duplicacyPassword")) or None)
    cache_key = _remote_cache_key(
        "storage-files",
        storage_id,
        snapshot_id,
        revision,
        bool(effective_password),
        hashlib.sha256((effective_password or "").encode("utf-8")).hexdigest() if effective_password else "",
    )
    cached = _remote_cache_get(cache_key)
    if cached is not None:
        return cached
    result = await with_temp_storage_session_list_files(
        storage=storage,
        snapshot_id=snapshot_id,
        revision=revision,
        password=effective_password,
    )
    if result.get("code") != 0:
        raise HTTPException(status_code=500, detail=result.get("stdout") or result.get("stderr") or "No se pudieron listar archivos")
    payload = {"ok": True, "files": result.get("files") or []}
    _remote_cache_set(cache_key, payload)
    return payload


@router.post("/api/storages/{storage_id}/restore")
async def restore_from_storage(storage_id: str, req: StorageRestoreRequest):
    if storage_id != req.storageId:
        raise HTTPException(status_code=400, detail="storageId de la URL y del body no coinciden")
    if storage_id in active_storage_restores:
        raise HTTPException(status_code=409, detail="Ya hay una restauración en ejecución para este storage")
    storage = get_storage_by_id(storage_id)
    if not storage:
        raise HTTPException(status_code=404, detail="Storage no encontrado")
    snapshot_id = (req.snapshotId or "").strip()
    if not snapshot_id:
        raise HTTPException(status_code=400, detail="snapshotId es obligatorio")
    restore_path = (req.restorePath or "").strip()
    if not restore_path:
        raise HTTPException(status_code=400, detail="Para restaurar desde un storage sin backup local debes indicar una ruta de restauración")

    effective_password = (req.password or "").strip() or (reveal_secret((storage.get("_secrets") or {}).get("duplicacyPassword")) or None)
    logger.info(
        "[Restore] Inicio storage=%s snapshotId=%s revision=%s destino=%s overwrite=%s threads=%s seleccion=%s",
        storage.get("name") or storage.get("label") or storage_id,
        snapshot_id,
        req.revision,
        restore_path,
        bool(req.overwrite),
        FIXED_DUPLICACY_THREADS,
        summarize_path_selection(req.patterns),
    )
    active_storage_restores[storage_id] = {
        "status": "running",
        "startedAt": datetime.now().isoformat(),
        "lastOutput": "Iniciando restauración...",
        "outputLines": [],
        "cancelRequested": False,
        "snapshotId": snapshot_id,
        "revision": req.revision,
        "restorePath": restore_path,
    }
    active_storage_restore_cancel_flags[storage_id] = False
    completed_storage_restores.pop(storage_id, None)

    async def run_restore_storage_task():
        result: Dict[str, Any] = {"code": -1, "stdout": "", "stderr": "Error no especificado"}
        task_started_monotonic = time.monotonic()

        def on_progress(text: str):
            if storage_id in active_storage_restores:
                clean = (text or "").rstrip("\r\n")
                if clean:
                    active_storage_restores[storage_id]["lastOutput"] = clean
                    active_storage_restores[storage_id].setdefault("outputLines", []).append(clean)

        def on_process_start(proc: Any):
            active_storage_restore_processes[storage_id] = proc
            if storage_id in active_storage_restores:
                active_storage_restores[storage_id]["pid"] = getattr(proc, "pid", None)

        try:
            await ensure_restore_target_initialized_from_storage(
                storage=storage,
                snapshot_id=snapshot_id,
                target_path=restore_path,
                password=effective_password,
            )
            result = await duplicacy_service.restore(
                restore_path,
                req.revision,
                overwrite=req.overwrite,
                password=effective_password,
                storage_name="default",
                extra_env=get_storage_record_env(storage, "default"),
                patterns=req.patterns or None,
                threads=FIXED_DUPLICACY_THREADS,
                on_progress=on_progress,
                on_process_start=on_process_start,
            )

            duration = round(time.monotonic() - task_started_monotonic, 2)
            was_cancelled = bool((active_storage_restores.get(storage_id) or {}).get("cancelRequested")) or bool(active_storage_restore_cancel_flags.get(storage_id))
            if result.get("code") != 0 and not was_cancelled:
                logger.error(
                    "[Restore] Fin storage=%s snapshotId=%s revision=%s resultado=ERROR codigo=%s duracion_s=%s",
                    storage.get("name") or storage_id,
                    snapshot_id,
                    req.revision,
                    result.get("code"),
                    duration,
                )
            else:
                logger.info(
                    "[Restore] Fin storage=%s snapshotId=%s revision=%s resultado=%s codigo=%s duracion_s=%s destino_real=%s",
                    storage.get("name") or storage_id,
                    snapshot_id,
                    req.revision,
                    "CANCELLED" if was_cancelled else "OK",
                    result.get("code"),
                    duration,
                    restore_path,
                )

            completed_storage_restores[storage_id] = {
                "done": True,
                "code": result.get("code", -1),
                "stdout": result.get("stdout", "") or "",
                "stderr": result.get("stderr", "") or "",
                "finishedAt": datetime.now().isoformat(),
                "canceled": was_cancelled,
                "restorePath": restore_path,
            }
        except Exception as exc:
            duration = round(time.monotonic() - task_started_monotonic, 2)
            logger.exception(
                "[Restore] Excepción inesperada storage=%s snapshotId=%s revision=%s duracion_s=%s",
                storage.get("name") or storage_id,
                snapshot_id,
                req.revision,
                duration,
            )
            completed_storage_restores[storage_id] = {
                "done": True,
                "code": result.get("code", -1),
                "stdout": result.get("stdout", "") or "",
                "stderr": str(exc),
                "finishedAt": datetime.now().isoformat(),
                "canceled": bool((active_storage_restores.get(storage_id) or {}).get("cancelRequested")) or bool(active_storage_restore_cancel_flags.get(storage_id)),
                "restorePath": restore_path,
            }
        finally:
            active_storage_restore_processes.pop(storage_id, None)
            active_storage_restore_cancel_flags.pop(storage_id, None)
            active_storage_restores.pop(storage_id, None)

    asyncio.create_task(run_restore_storage_task())
    return {"ok": True}


@router.post("/api/storages/{storage_id}/restore/cancel")
async def cancel_restore_from_storage(storage_id: str, req: StorageRestoreCancelRequest):
    if storage_id != req.storageId:
        raise HTTPException(status_code=400, detail="storageId de la URL y del body no coinciden")
    info = active_storage_restores.get(storage_id)
    if not info:
        raise HTTPException(status_code=404, detail="No hay restauración en ejecución para este storage")
    info["cancelRequested"] = True
    info["lastOutput"] = "Cancelación solicitada por el usuario..."
    info.setdefault("outputLines", []).append("⏹ Cancelación solicitada por el usuario...")
    proc = active_storage_restore_processes.get(storage_id)
    if not proc:
        raise HTTPException(status_code=409, detail="No se encontró el proceso de restauración en ejecución")
    active_storage_restore_cancel_flags[storage_id] = True
    _terminate_storage_restore_process(proc)
    logger.warning("[Restore] Cancelación solicitada storage=%s", storage_id)
    return {"ok": True, "message": "Cancelación de restauración solicitada"}


@router.get("/api/storages/{storage_id}/restore/progress")
async def restore_from_storage_progress(storage_id: str):
    async def event_generator():
        sent_lines = 0
        while True:
            info = active_storage_restores.get(storage_id)
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

            completed = completed_storage_restores.pop(storage_id, None)
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

