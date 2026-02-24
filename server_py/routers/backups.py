import asyncio
import os
import signal
import time
import json
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from server_py.utils.config_store import repositories as repositories_config
from server_py.models.schemas import RepoCreate, RepoUpdate, BackupStart, BackupCancelRequest
from server_py.services.duplicacy import service as duplicacy_service
from server_py.core.helpers import (
    sanitize_repo, get_storage_by_id, build_destination_from_storage_ref, 
    resolve_repo_destination, get_storage_env, get_primary_storage, 
    describe_storage, summarize_path_selection, get_storage_record_env, 
    build_backup_change_summary, FIXED_DUPLICACY_THREADS,
    active_backups, completed_backups, active_backup_processes, 
    scheduler_task, scheduler_running, remote_storage_list_cache,
    normalize_content_selection, normalize_schedule_config,
    get_repo_duplicacy_password,
    build_destination_from_update, _repo_snapshot_revisions,
    sync_repo_filters_file,
    logger
)

router = APIRouter(tags=["backups"])

# --- Repositories / Backup Jobs ---

@router.get("/api/repos")
async def get_repos():
    repos = repositories_config.read()
    return {"ok": True, "repos": [sanitize_repo(r) for r in repos]}


@router.post("/api/repos/validate")
async def validate_repo(repo: RepoCreate):
    destination = None
    if repo.storageId:
        linked_storage = get_storage_by_id(repo.storageId)
        if not linked_storage:
            raise HTTPException(status_code=404, detail="Storage seleccionado no encontrado")
        destination = build_destination_from_storage_ref(linked_storage)
    else:
        destination = resolve_repo_destination(repo)

    init_password = repo.password or (destination.get("storageDuplicacyPassword") if destination else None)
    encrypt_enabled = repo.encrypt if repo.encrypt is not None else (True if init_password else False)

    # Asegurar que las credenciales cubran el alias "default" usado en init temporal
    extra_env = dict(destination.get("extraEnv") or {})
    linked_storage = get_storage_by_id(repo.storageId) if repo.storageId else None
    if linked_storage or (repo.destinationType == "wasabi"):
        src = linked_storage or {
            "type": "wasabi",
            "_secrets": {
                "accessId": repo.wasabiAccessId,
                "accessKey": repo.wasabiAccessKey
            }
        }
        extra_env.update(get_storage_record_env(src, "default"))

    # Use a temporary directory for validation
    with tempfile.TemporaryDirectory() as tmp_dir:
        logger.info(f"[RepoValidate] Validando init en {tmp_dir} con snapshotId={repo.snapshotId}")
        result = await duplicacy_service.init(
            tmp_dir,
            repo.snapshotId,
            destination["storageUrl"],
            password=init_password,
            encrypt=encrypt_enabled,
            extra_env=extra_env
        )

        logger.info(f"[RepoValidate] Respuesta validación: code={result['code']}")

        if result["code"] != 0:
            detail = (result.get("stdout") or result.get("stderr") or "Duplicacy init validation failed")
            # Reuse logic for common errors if needed, but for validation we just want to know it failed
            return {"ok": False, "detail": detail}

    return {"ok": True, "message": "Configuración válida"}


@router.get("/api/repos/{repo_id}")
async def get_repo(repo_id: str):
    repos_data = repositories_config.read()
    repo = next((r for r in repos_data if r["id"] == repo_id), None)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return {"ok": True, "repo": sanitize_repo(repo)}

@router.post("/api/repos")
async def create_repo(repo: RepoCreate):
    destination = None
    linked_storage = None
    if repo.storageId:
        linked_storage = get_storage_by_id(repo.storageId)
        if not linked_storage:
            raise HTTPException(status_code=404, detail="Storage seleccionado no encontrado")
        destination = build_destination_from_storage_ref(linked_storage)
    else:
        destination = resolve_repo_destination(repo)
    repo_path = Path(repo.path)
    if not repo_path.exists():
        repo_path.mkdir(parents=True, exist_ok=True)

    repo_id = str(uuid.uuid4())
    # Use part of the UUID as storage name to avoid conflicts in .duplicacy/config
    duplicacy_storage_name = f"s-{repo_id[:8]}"

    # Check if already initialized
    is_already_init = (repo_path / ".duplicacy").exists()

    init_password = repo.password or (destination.get("storageDuplicacyPassword") if destination else None)
    encrypt_enabled = repo.encrypt if repo.encrypt is not None else (True if init_password else False)

    # Cargar variables de entorno del storage, asegurando que cubran el alias dinámico
    extra_env = dict(destination.get("extraEnv") or {})
    if linked_storage or (repo.destinationType == "wasabi"):
        src = linked_storage or {
            "type": "wasabi",
            "_secrets": {
                "accessId": repo.wasabiAccessId,
                "accessKey": repo.wasabiAccessKey
            }
        }
        # Inyectar credenciales específicamente para el alias que vamos a usar en Duplicacy
        extra_env.update(get_storage_record_env(src, duplicacy_storage_name))

    if is_already_init:
        logger.info(f"[RepoInit] Carpeta ya inicializada. Usando 'add' para snapshotId={repo.snapshotId} en {repo_path}")
        result = await duplicacy_service.add_storage(
            str(repo_path),
            duplicacy_storage_name,
            repo.snapshotId,
            destination["storageUrl"],
            password=init_password,
            encrypt=encrypt_enabled,
            extra_env=extra_env
        )
    else:
        logger.info(f"[RepoInit] Iniciando init en {repo_path} con snapshotId={repo.snapshotId}")
        # Para init, duplicacy usa "default" como nombre interno
        init_env = dict(extra_env)
        init_env.update(get_storage_record_env(src, "default"))
        result = await duplicacy_service.init(
            str(repo_path),
            repo.snapshotId,
            destination["storageUrl"],
            password=init_password,
            encrypt=encrypt_enabled,
            extra_env=init_env
        )
        # duplicacy init sets name as "default"
        duplicacy_storage_name = "default"


    logger.info(f"[RepoInit] Respuesta: code={result['code']}")

    if result["code"] != 0:
        detail = (result.get("stdout") or result.get("stderr") or "Duplicacy setup failed")
        if "likely to have been initialized with a password before" in detail:
            detail = (
                "Ese storage de Duplicacy parece estar cifrado con una contraseña previa. "
                "Usa 'Importar repositorio existente (Wasabi)' y escribe la contraseña de Duplicacy correcta."
            )
        raise HTTPException(status_code=500, detail=detail)

    storages = [destination["storage"]]
    # Ensure storage record has the correct name
    storages[0]["name"] = duplicacy_storage_name

    secrets: Dict[str, Dict[str, str]] = destination.get("secrets") or {}
    # Remap secrets to the correct storage name if they were using "default" or other keys
    if secrets:
        remapped_secrets = {}
        for old_key, val in secrets.items():
            remapped_secrets[duplicacy_storage_name] = val
        secrets = remapped_secrets

    repos_data = repositories_config.read()
    new_repo = {
        "id": repo_id,
        "name": repo.name,
        "path": str(repo_path),
        "snapshotId": repo.snapshotId,
        "duplicacyStorageName": duplicacy_storage_name,
        "storageUrl": destination["storageUrl"],
        "storageRefId": destination.get("storageRefId"),
        "storages": storages,
        "replication": {
            "enabled": False,
            "mode": None,
            "from": None,
            "to": None,
        },
        "encrypted": bool(init_password),
        "createdAt": datetime.now().isoformat(),
        "importedFromExisting": bool(repo.importExisting),
        "lastBackup": None,
        "lastBackupStatus": None,
        "lastBackupSummary": None,
        "contentSelection": normalize_content_selection(repo.contentSelection),
        "schedule": normalize_schedule_config(repo.schedule),
    }
    if secrets:
        new_repo["_secrets"] = secrets
    repos_data.append(new_repo)
    repositories_config.write(repos_data)
    
    return {"ok": True, "repo": sanitize_repo(new_repo)}



@router.put("/api/repos/{repo_id}")
async def update_repo(repo_id: str, req: RepoUpdate):
    repos_data = repositories_config.read()
    idx = next((i for i, r in enumerate(repos_data) if r["id"] == repo_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo = dict(repos_data[idx])
    changed_destination = False

    if req.name is not None:
        repo["name"] = req.name.strip() or repo.get("name")
    
    if req.contentSelection is not None:
        repo["contentSelection"] = normalize_content_selection(req.contentSelection)

    if req.schedule is not None:
        repo["schedule"] = normalize_schedule_config(req.schedule, repo.get("schedule"))

    repos_data[idx] = repo
    repositories_config.write(repos_data)

    return {"ok": True, "repo": sanitize_repo(repo)}


@router.delete("/api/repos/{repo_id}")
async def delete_repo(repo_id: str):
    if repo_id in active_backups:
        raise HTTPException(
            status_code=409, 
            detail="No se puede eliminar el repositorio mientras hay un backup en ejecución. Cancélalo primero."
        )
    
    repos_data = repositories_config.read()
    repo = next((r for r in repos_data if r["id"] == repo_id), None)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    repos_data = [r for r in repos_data if r["id"] != repo_id]
    repositories_config.write(repos_data)
    return {"ok": True, "removed": sanitize_repo(repo)}

# --- Backup ---

@router.post("/api/backup/start")
async def start_backup(req: BackupStart):
    repos_data = repositories_config.read()
    repo = next((r for r in repos_data if r["id"] == req.repoId), None)
    
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if req.repoId in active_backups:
        raise HTTPException(status_code=409, detail="Backup already running")

    # Inyectar contraseña desde los secretos si no se provee por el POST
    if not req.password:
        req.password = get_repo_duplicacy_password(repo)

    effective_threads = FIXED_DUPLICACY_THREADS


    trigger = (req.trigger or "manual").strip().lower()
    if trigger not in {"manual", "scheduler"}:
        trigger = "manual"

    active_backups[req.repoId] = {
        "status": "running",
        "startedAt": datetime.now().isoformat(),
        "lastOutput": "Iniciando...",
        "outputLines": [],
        "cancelRequested": False,
        "trigger": trigger,
    }
    completed_backups.pop(req.repoId, None)
    logger.info(
        "[Backup] Solicitud aceptada repo=%s nombre=%s trigger=%s origen=%s destino=%s threads=%s seleccion=%s",
        req.repoId,
        repo.get("name", "—"),
        trigger,
        repo.get("path", "—"),
        describe_storage(repo),
        effective_threads,
        summarize_path_selection(repo.get("contentSelection")),
    )

    async def run_backup_task():
        started_monotonic = time.monotonic()
        pre_latest_revision: Optional[int] = None
        primary_storage_name: Optional[str] = None

        def on_progress(text):
            if req.repoId in active_backups:
                clean = (text or "").rstrip("\r\n")
                if clean:
                    active_backups[req.repoId]["lastOutput"] = clean
                    active_backups[req.repoId].setdefault("outputLines", []).append(clean)

        def on_process_start(proc):
            active_backup_processes[req.repoId] = proc
            if req.repoId in active_backups:
                active_backups[req.repoId]["pid"] = getattr(proc, "pid", None)

        result = {"code": -1, "stdout": "", "stderr": "Error no especificado"}
        try:
            logger.info(
                "[Backup] Inicio repo=%s nombre=%s trigger=%s origen=%s",
                req.repoId,
                repo.get("name", "—"),
                trigger,
                repo.get("path", "—"),
            )
            primary = get_primary_storage(repo)
            if not primary:
                result = {"code": -1, "stdout": "", "stderr": "Repo sin storage configurado"}
            else:
                # Prioritize the specific storage name saved during init/add
                primary_storage_name = repo.get("duplicacyStorageName") or primary.get("name")
                try:
                    pre_list = await duplicacy_service.list_snapshots(
                        repo["path"],
                        password=req.password,
                        storage_name=primary_storage_name,
                        extra_env=get_storage_env(repo, primary_storage_name),
                    )
                    if pre_list.get("code") == 0:
                        pre_revs = _repo_snapshot_revisions(pre_list.get("snapshots") or [], str(repo.get("snapshotId") or ""))
                        pre_latest_revision = pre_revs[-1] if pre_revs else None
                except Exception:
                    logger.exception("[Backup] No se pudo obtener revision previa repo=%s", req.repoId)

                try:
                    sync_repo_filters_file(repo)
                except Exception as exc:
                    result = {"code": -1, "stdout": "", "stderr": f"No se pudo preparar filtros del backup: {exc}"}
                else:
                    if req.repoId in active_backups:
                        prefix = "Backup programado" if trigger == "scheduler" else "Backup"
                        active_backups[req.repoId]["lastOutput"] = f"{prefix} en {primary.get('label', primary['name'])}..."

                    result = await duplicacy_service.backup(
                        repo["path"],
                        password=req.password,
                        threads=effective_threads,
                        on_progress=on_progress,
                        on_process_start=on_process_start,
                        storage_name=primary_storage_name,
                        extra_env=get_storage_env(repo, primary_storage_name)
                    )

                    replication = repo.get("replication") or {}
                    if result["code"] == 0 and replication.get("enabled") and replication.get("to"):
                        from_storage = replication.get("from") or primary.get("name")
                        to_storage = replication["to"]
                        if req.repoId in active_backups:
                            active_backups[req.repoId]["lastOutput"] = "Replicando backup a Wasabi S3..."
                        logger.info(
                            "[Backup] Replicacion repo=%s desde=%s hacia=%s",
                            req.repoId,
                            from_storage,
                            to_storage,
                        )

                        copy_result = await duplicacy_service.copy(
                            repo["path"],
                            from_storage=from_storage,
                            to_storage=to_storage,
                            password=req.password,
                            on_progress=on_progress,
                            on_process_start=on_process_start,
                            extra_env=get_storage_env(repo, to_storage)
                        )
                        if copy_result["code"] != 0:
                            result = {
                                "code": copy_result["code"],
                                "stdout": (result.get("stdout") or "") + "\n\n--- COPY TO WASABI ---\n" + (copy_result.get("stdout") or copy_result.get("stderr") or ""),
                                "stderr": copy_result.get("stderr", "")
                            }
                        else:
                            result["stdout"] = (result.get("stdout") or "") + "\n\n--- COPY TO WASABI OK ---\n" + (copy_result.get("stdout") or "")

                    if result.get("code") == 0 and primary_storage_name:
                        try:
                            backup_summary = await build_backup_change_summary(
                                repo,
                                storage_name=primary_storage_name,
                                password=req.password,
                                pre_latest_revision=pre_latest_revision,
                            )
                            if req.repoId in active_backups and backup_summary:
                                active_backups[req.repoId]["backupSummary"] = backup_summary
                            if backup_summary.get("ok"):
                                logger.info(
                                    "[Backup] Resumen repo=%s rev=%s prev=%s total=%s nuevos=%s cambiados=%s eliminados=%s",
                                    req.repoId,
                                    backup_summary.get("createdRevision"),
                                    backup_summary.get("previousRevision"),
                                    backup_summary.get("fileCount", "—"),
                                    backup_summary.get("new"),
                                    backup_summary.get("changed"),
                                    backup_summary.get("deleted"),
                                )
                                samples = backup_summary.get("samples") or {}
                                sample_parts = []
                                for key, label in (("new", "nuevos"), ("changed", "cambiados"), ("deleted", "eliminados")):
                                    vals = samples.get(key) or []
                                    if vals:
                                        sample_parts.append(f"{label}: {', '.join(vals[:5])}")
                                if sample_parts:
                                    logger.info("[Backup] Muestra repo=%s %s", req.repoId, " | ".join(sample_parts))
                            else:
                                logger.warning(
                                    "[Backup] Resumen no disponible repo=%s motivo=%s",
                                    req.repoId,
                                    backup_summary.get("message") or backup_summary.get("detail") or "desconocido",
                                )
                        except Exception:
                            logger.exception("[Backup] Error calculando resumen de cambios repo=%s", req.repoId)

            # Update repo info
            all_repos = repositories_config.read()
            for r in all_repos:
                if r["id"] == req.repoId:
                    r["lastBackup"] = datetime.now().isoformat()
                    was_cancelled = bool((active_backups.get(req.repoId) or {}).get("cancelRequested"))
                    final_status = "cancelled" if was_cancelled else ("success" if result["code"] == 0 else "error")
                    r["lastBackupStatus"] = final_status
                    r["lastBackupTrigger"] = trigger
                    r["lastBackupOutput"] = result["stdout"][-500:]
                    r["lastBackupSummary"] = (active_backups.get(req.repoId) or {}).get("backupSummary")
                    if isinstance(r.get("schedule"), dict):
                        r["schedule"]["lastRunAt"] = datetime.now().isoformat()
                        r["schedule"]["lastRunStatus"] = final_status
                        if final_status == "success":
                            r["schedule"]["lastError"] = None
                        elif result.get("stderr"):
                            r["schedule"]["lastError"] = (result.get("stderr") or result.get("stdout") or "")[:300]
                    break
            repositories_config.write(all_repos)
            duration = round(time.monotonic() - started_monotonic, 2)
            was_cancelled = bool((active_backups.get(req.repoId) or {}).get("cancelRequested"))
            logger.info(
                "[Backup] Fin repo=%s nombre=%s resultado=%s codigo=%s duracion_s=%s",
                req.repoId,
                repo.get("name", "—"),
                "CANCELLED" if was_cancelled else ("OK" if result.get("code") == 0 else "ERROR"),
                result.get("code"),
                duration,
            )
            if trigger == "scheduler":
                logger.info(
                    "[Scheduler] Fin backup repo=%s nombre=%s resultado=%s duracion_s=%s",
                    req.repoId,
                    repo.get("name", "—"),
                    "CANCELLED" if was_cancelled else ("OK" if result.get('code') == 0 else "ERROR"),
                    duration,
                )
            completed_backups[req.repoId] = {
                "done": True,
                "code": result.get("code", -1),
                "stdout": result.get("stdout", "") or "",
                "stderr": result.get("stderr", "") or "",
                "finishedAt": datetime.now().isoformat(),
                "canceled": was_cancelled,
                "backupSummary": (active_backups.get(req.repoId) or {}).get("backupSummary"),
                "trigger": trigger,
            }
        except Exception:
            duration = round(time.monotonic() - started_monotonic, 2)
            logger.exception(
                "[Backup] Excepcion inesperada repo=%s nombre=%s duracion_s=%s",
                req.repoId,
                repo.get("name", "—"),
                duration,
            )
            completed_backups[req.repoId] = {
                "done": True,
                "code": result.get("code", -1),
                "stdout": result.get("stdout", "") or "",
                "stderr": result.get("stderr", "") or "",
                "finishedAt": datetime.now().isoformat(),
                "backupSummary": (active_backups.get(req.repoId) or {}).get("backupSummary"),
                "trigger": trigger,
            }
        finally:
            # Invalidate repo-related caches after backup attempt (success or error)
            # to ensure the next list call gets fresh data
            keys_to_remove = []
            for k in remote_storage_list_cache.keys():
                if k.startswith(f"repo-snapshots||{req.repoId}||") or k.startswith(f"repo-files||{req.repoId}||"):
                    keys_to_remove.append(k)
            for k in keys_to_remove:
                remote_storage_list_cache.pop(k, None)

            active_backup_processes.pop(req.repoId, None)
            active_backups.pop(req.repoId, None)

    asyncio.create_task(run_backup_task())
    return {"ok": True}

@router.get("/api/backup/status/{repo_id}")
async def get_backup_status(repo_id: str):
    info = active_backups.get(repo_id)
    if not info:
        return {"ok": True, "running": False}
    return {"ok": True, "running": True, **info}


@router.post("/api/backup/cancel")
async def cancel_backup(req: BackupCancelRequest):
    info = active_backups.get(req.repoId)
    if not info:
        raise HTTPException(status_code=404, detail="No hay backup en ejecución para ese repositorio")

    proc = active_backup_processes.get(req.repoId)
    if not proc:
        raise HTTPException(status_code=409, detail="No se encontró el proceso del backup en ejecución")

    active_backups[req.repoId]["cancelRequested"] = True
    active_backups[req.repoId]["lastOutput"] = "Cancelación solicitada por el usuario..."
    active_backups[req.repoId].setdefault("outputLines", []).append("⏹ Cancelación solicitada por el usuario...")

    try:
        proc.terminate()
    except Exception:
        pid = getattr(proc, "pid", None)
        try:
            if pid:
                os.kill(pid, signal.SIGTERM)
            else:
                raise RuntimeError("PID no disponible")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"No se pudo cancelar el backup: {exc}")

    logger.info("[Backup] Cancelacion solicitada repo=%s pid=%s", req.repoId, getattr(proc, "pid", None))
    return {"ok": True, "message": "Cancelación solicitada"}

@router.get("/api/backup/progress/{repo_id}")
async def backup_progress(repo_id: str):
    async def event_generator():
        sent_lines = 0
        while True:
            info = active_backups.get(repo_id)
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

            completed = completed_backups.pop(repo_id, None)
            if completed:
                payload = {
                    "done": True,
                    "success": completed.get("code", -1) == 0 and not completed.get("canceled"),
                    "canceled": bool(completed.get("canceled")),
                    "code": completed.get("code", -1),
                    "finalOutput": completed.get("stdout", "") or completed.get("stderr", ""),
                    "backupSummary": completed.get("backupSummary"),
                }
                yield f"data: {json.dumps(payload)}\n\n"
                break

            yield f"data: {json.dumps({'done': True})}\n\n"
            await asyncio.sleep(1)
            break

    return StreamingResponse(event_generator(), media_type="text/event-stream")

