import os
import uuid
import asyncio
import hashlib
import hmac
import time
import signal
import tempfile
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
class RepoCreate(BaseModel):
    name: str
    path: str
    snapshotId: str
    importExisting: Optional[bool] = False
    storageId: Optional[str] = None
    destinationType: Optional[str] = "local"  # local | wasabi
    storageUrl: Optional[str] = None  # legacy single-destination field
    localStoragePath: Optional[str] = None
    wasabiEnabled: Optional[bool] = False
    wasabiEndpoint: Optional[str] = None
    wasabiRegion: Optional[str] = None
    wasabiBucket: Optional[str] = None
    wasabiDirectory: Optional[str] = None
    wasabiAccessId: Optional[str] = None
    wasabiAccessKey: Optional[str] = None
    password: Optional[str] = None
    encrypt: Optional[bool] = None
    contentSelection: Optional[List[str]] = None
    schedule: Optional[Dict[str, Any]] = None

class BackupStart(BaseModel):
    repoId: str
    password: Optional[str] = None
    threads: Optional[int] = None
    trigger: Optional[str] = None  # manual | scheduler


class BackupCancelRequest(BaseModel):
    repoId: str

class RestoreRequest(BaseModel):
    repoId: str
    revision: int
    overwrite: Optional[bool] = True
    password: Optional[str] = None
    storageName: Optional[str] = None
    restorePath: Optional[str] = None
    patterns: Optional[List[str]] = None


class StorageRestoreRequest(BaseModel):
    storageId: str
    snapshotId: str
    revision: int
    overwrite: Optional[bool] = True
    password: Optional[str] = None
    restorePath: Optional[str] = None
    patterns: Optional[List[str]] = None


class WasabiConnectionTest(BaseModel):
    endpoint: str
    region: str
    bucket: str
    accessId: str
    accessKey: str


class WasabiSnapshotDetectRequest(BaseModel):
    endpoint: str
    region: str
    bucket: str
    directory: Optional[str] = None
    accessId: str
    accessKey: str
    password: Optional[str] = None


class RepoUpdate(BaseModel):
    name: Optional[str] = None
    path: Optional[str] = None
    snapshotId: Optional[str] = None
    destinationType: Optional[str] = None  # local | wasabi
    localStoragePath: Optional[str] = None
    wasabiEndpoint: Optional[str] = None
    wasabiRegion: Optional[str] = None
    wasabiBucket: Optional[str] = None
    wasabiDirectory: Optional[str] = None
    wasabiAccessId: Optional[str] = None
    wasabiAccessKey: Optional[str] = None
    contentSelection: Optional[List[str]] = None
    schedule: Optional[Dict[str, Any]] = None


class StorageCreate(BaseModel):
    name: str
    type: str  # local | wasabi
    localPath: Optional[str] = None
    endpoint: Optional[str] = None
    region: Optional[str] = None
    bucket: Optional[str] = None
    directory: Optional[str] = None
    accessId: Optional[str] = None
    accessKey: Optional[str] = None
    duplicacyPassword: Optional[str] = None


class StorageUpdate(BaseModel):
    name: Optional[str] = None
    localPath: Optional[str] = None
    endpoint: Optional[str] = None
    region: Optional[str] = None
    bucket: Optional[str] = None
    directory: Optional[str] = None
    accessId: Optional[str] = None
    accessKey: Optional[str] = None
    duplicacyPassword: Optional[str] = None
    clearDuplicacyPassword: Optional[bool] = False

# ─── STATE ────────────────────────────────────────────────
active_backups: Dict[str, Dict[str, Any]] = {}
completed_backups: Dict[str, Dict[str, Any]] = {}
active_backup_processes: Dict[str, Any] = {}
scheduler_task: Optional[asyncio.Task] = None
scheduler_running: bool = False
FIXED_DUPLICACY_THREADS = 16
REMOTE_LIST_CACHE_TTL_SECONDS = 300
remote_storage_list_cache: Dict[str, Dict[str, Any]] = {}

INTERNAL_SECRET_KEYS = {"_secrets", "wasabiAccessKey", "wasabiAccessId"}
INTERNAL_STORAGE_SECRET_KEYS = {"_secrets", "accessId", "accessKey", "duplicacyPassword"}


def _remote_cache_key(*parts: Any) -> str:
    return "||".join(str(p) for p in parts)


def _remote_cache_get(key: str) -> Optional[Any]:
    item = remote_storage_list_cache.get(key)
    if not item:
        return None
    ts = float(item.get("ts") or 0)
    if (time.time() - ts) > REMOTE_LIST_CACHE_TTL_SECONDS:
        remote_storage_list_cache.pop(key, None)
        return None
    return item.get("value")


def _remote_cache_set(key: str, value: Any) -> None:
    remote_storage_list_cache[key] = {"ts": time.time(), "value": value}


def sanitize_repo(repo: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(repo)
    for key in INTERNAL_SECRET_KEYS:
        sanitized.pop(key, None)
    return sanitized


def sanitize_storage(storage: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(storage)
    for key in INTERNAL_STORAGE_SECRET_KEYS:
        sanitized.pop(key, None)
    # Expose safe flags for UI
    secrets = storage.get("_secrets") or {}
    sanitized["hasWasabiCredentials"] = bool(secrets.get("accessId") and secrets.get("accessKey"))
    sanitized["hasDuplicacyPassword"] = bool(secrets.get("duplicacyPassword"))
    return sanitized


def get_storage_by_id(storage_id: str) -> Optional[Dict[str, Any]]:
    storages = config_store.storages.read()
    return next((s for s in storages if s.get("id") == storage_id), None)


def get_repo_storage(repo: Dict[str, Any], storage_name: str) -> Optional[Dict[str, Any]]:
    for storage in repo.get("storages", []):
        if storage.get("name") == storage_name:
            return storage
    return None


def get_primary_storage(repo: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    storages = repo.get("storages", [])
    if not storages:
        if repo.get("storageUrl"):
            return {"name": "default", "type": "legacy", "url": repo["storageUrl"], "isDefault": True}
        return None
    for storage in storages:
        if storage.get("isDefault"):
            return storage
    return storages[0]


def summarize_path_selection(paths: Optional[List[str]]) -> str:
    items = [str(p or "").strip() for p in (paths or []) if str(p or "").strip()]
    if not items:
        return "todo"
    dirs = sum(1 for p in items if p.endswith("/") or p.endswith("\\"))
    files = len(items) - dirs
    preview = ", ".join(items[:4])
    if len(items) > 4:
        preview += f", +{len(items) - 4} más"
    return f"{len(items)} elemento(s) ({dirs} carpetas, {files} ficheros): {preview}"


def describe_storage(repo: Dict[str, Any], storage_name: Optional[str] = None) -> str:
    primary = get_repo_storage(repo, storage_name) or get_primary_storage(repo) or {}
    label = primary.get("label") or primary.get("name") or "default"
    url = primary.get("url") or repo.get("storageUrl") or "—"
    return f"{label} -> {url}"


SCHEDULE_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
SCHEDULE_WEEKDAY_INDEX = {day: idx for idx, day in enumerate(SCHEDULE_WEEKDAYS)}


def _normalize_schedule_time(value: Any) -> str:
    text = str(value or "").strip()
    try:
        parts = text.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("out of range")
        return f"{hour:02d}:{minute:02d}"
    except Exception:
        return "23:00"


def _parse_schedule_time_parts(time_str: str) -> tuple[int, int]:
    h, m = (time_str or "23:00").split(":")
    return int(h), int(m)


def compute_next_run_for_schedule(schedule: Dict[str, Any], now: Optional[datetime] = None) -> Optional[datetime]:
    if not schedule or not schedule.get("enabled"):
        return None
    now = now or datetime.now()
    mode = str(schedule.get("type") or "daily").strip().lower()
    hour, minute = _parse_schedule_time_parts(str(schedule.get("time") or "23:00"))
    base_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if mode == "weekly":
        days = [d for d in (schedule.get("days") or []) if d in SCHEDULE_WEEKDAY_INDEX]
        if not days:
            days = ["mon"]
        current_wd = now.weekday()
        candidates: List[datetime] = []
        for day in days:
            target_wd = SCHEDULE_WEEKDAY_INDEX[day]
            delta_days = (target_wd - current_wd) % 7
            candidate = base_today + timedelta(days=delta_days)
            if candidate <= now:
                candidate += timedelta(days=7)
            candidates.append(candidate)
        return min(candidates) if candidates else None

    # default daily
    candidate = base_today
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def normalize_schedule_config(schedule_raw: Optional[Dict[str, Any]], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    existing = dict(existing or {})
    raw = dict(schedule_raw or {})
    enabled = bool(raw.get("enabled", existing.get("enabled", False)))
    mode = str(raw.get("type", existing.get("type", "daily")) or "daily").strip().lower()
    if mode not in {"daily", "weekly"}:
        mode = "daily"
    time_str = _normalize_schedule_time(raw.get("time", existing.get("time", "23:00")))
    days_raw = raw.get("days", existing.get("days", []))
    days = []
    for d in (days_raw or []):
        token = str(d or "").strip().lower()[:3]
        if token in SCHEDULE_WEEKDAY_INDEX and token not in days:
            days.append(token)
    if mode == "weekly" and not days:
        days = ["mon"]

    threads_val = raw.get("threads", existing.get("threads"))
    threads: Optional[int] = None
    try:
        if threads_val not in (None, "", False):
            parsed = int(threads_val)
            if 1 <= parsed <= 64:
                threads = parsed
    except Exception:
        threads = None

    normalized = {
        "enabled": enabled,
        "type": mode,
        "time": time_str,
        "days": days if mode == "weekly" else [],
        "threads": threads,
        "lastRunAt": existing.get("lastRunAt"),
        "lastRunStatus": existing.get("lastRunStatus"),
        "lastError": existing.get("lastError"),
    }
    next_run = compute_next_run_for_schedule(normalized)
    normalized["nextRunAt"] = next_run.isoformat() if next_run else None
    return normalized


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


async def scheduler_tick():
    repos_data = config_store.repositories.read()
    changed = False
    now = datetime.now()

    for repo in repos_data:
        schedule = repo.get("schedule")
        if not isinstance(schedule, dict):
            continue
        if not schedule.get("enabled"):
            # keep nextRunAt limpio si desactivado
            if schedule.get("nextRunAt") is not None:
                schedule["nextRunAt"] = None
                changed = True
            continue

        # Normalizar silenciosamente schedules antiguos/incompletos
        normalized = normalize_schedule_config(schedule, schedule)
        if normalized != schedule:
            repo["schedule"] = normalized
            schedule = normalized
            changed = True

        next_run = _parse_iso_datetime(schedule.get("nextRunAt"))
        if next_run is None:
            next_run_dt = compute_next_run_for_schedule(schedule, now)
            schedule["nextRunAt"] = next_run_dt.isoformat() if next_run_dt else None
            changed = True
            next_run = next_run_dt

        if repo.get("id") in active_backups:
            continue
        if not next_run or next_run > now:
            continue

        threads = schedule.get("threads")
        logger.info(
            "[Scheduler] Lanzando backup repo=%s nombre=%s tipo=%s hora=%s threads=%s",
            repo.get("id"),
            repo.get("name", "—"),
            schedule.get("type"),
            schedule.get("time"),
            threads if threads is not None else "auto",
        )
        try:
            await start_backup(BackupStart(repoId=repo["id"], threads=threads, trigger="scheduler"))
            schedule["lastRunAt"] = now.isoformat()
            schedule["lastRunStatus"] = "queued"
            schedule["lastError"] = None
            next_run_dt = compute_next_run_for_schedule(schedule, now + timedelta(seconds=1))
            schedule["nextRunAt"] = next_run_dt.isoformat() if next_run_dt else None
            changed = True
            logger.info(
                "[Scheduler] Backup encolado repo=%s nombre=%s proxima=%s",
                repo.get("id"),
                repo.get("name", "—"),
                schedule.get("nextRunAt") or "—",
            )
        except HTTPException as exc:
            schedule["lastRunAt"] = now.isoformat()
            schedule["lastRunStatus"] = "error"
            schedule["lastError"] = str(exc.detail)
            # Recalcular siguiente ejecución para evitar bucle de reintento continuo
            next_run_dt = compute_next_run_for_schedule(schedule, now + timedelta(seconds=60))
            schedule["nextRunAt"] = next_run_dt.isoformat() if next_run_dt else None
            changed = True
            logger.warning(
                "[Scheduler] No se pudo lanzar backup repo=%s nombre=%s detalle=%s",
                repo.get("id"),
                repo.get("name", "—"),
                exc.detail,
            )
        except Exception:
            schedule["lastRunAt"] = now.isoformat()
            schedule["lastRunStatus"] = "error"
            schedule["lastError"] = "Error inesperado lanzando el backup programado"
            next_run_dt = compute_next_run_for_schedule(schedule, now + timedelta(seconds=60))
            schedule["nextRunAt"] = next_run_dt.isoformat() if next_run_dt else None
            changed = True
            logger.exception("[Scheduler] Error inesperado repo=%s", repo.get("id"))

    if changed:
        config_store.repositories.write(repos_data)


async def scheduler_loop():
    global scheduler_running
    scheduler_running = True
    logger.info("[Scheduler] Iniciado (MVP) — comprobación cada 30s")
    try:
        while True:
            try:
                await scheduler_tick()
            except Exception:
                logger.exception("[Scheduler] Error en ciclo")
            await asyncio.sleep(30)
    except asyncio.CancelledError:
        logger.info("[Scheduler] Detenido")
        raise
    finally:
        scheduler_running = False


def _repo_snapshot_revisions(snapshots: List[Dict[str, Any]], snapshot_id: str) -> List[int]:
    revs = []
    for s in snapshots or []:
        try:
            if s.get("id") == snapshot_id:
                revs.append(int(s.get("revision")))
        except Exception:
            continue
    return sorted(set(revs))


def _build_file_signature_map(file_items: List[Dict[str, Any]]) -> Dict[str, str]:
    sigs: Dict[str, str] = {}
    for item in file_items or []:
        path = str(item.get("path") or "").strip()
        if not path or path.endswith("/") or path.endswith("\\"):
            continue
        sigs[path] = str(item.get("raw") or path)
    return sigs


def _sample_paths(items: List[str], limit: int = 12) -> List[str]:
    if not items:
        return []
    return items[:limit]


async def build_backup_change_summary(
    repo: Dict[str, Any],
    *,
    storage_name: str,
    password: Optional[str],
    pre_latest_revision: Optional[int] = None,
) -> Dict[str, Any]:
    extra_env = get_storage_env(repo, storage_name)
    list_result = await duplicacy_service.list_snapshots(
        repo["path"],
        password=password,
        storage_name=storage_name,
        extra_env=extra_env,
    )
    if list_result.get("code") != 0:
        return {
            "ok": False,
            "message": "No se pudieron consultar snapshots tras el backup",
            "detail": list_result.get("stdout") or list_result.get("stderr") or "",
        }

    revisions = _repo_snapshot_revisions(list_result.get("snapshots") or [], str(repo.get("snapshotId") or ""))
    if not revisions:
        return {"ok": False, "message": "No se encontraron revisiones del snapshot"}

    latest_revision = revisions[-1]
    previous_revision = None
    if pre_latest_revision is not None and pre_latest_revision in revisions and pre_latest_revision != latest_revision:
        previous_revision = pre_latest_revision
    elif len(revisions) >= 2:
        previous_revision = revisions[-2]

    if pre_latest_revision is not None and latest_revision == pre_latest_revision:
        return {
            "ok": True,
            "createdRevision": latest_revision,
            "previousRevision": previous_revision,
            "changed": 0,
            "new": 0,
            "deleted": 0,
            "unchanged": True,
            "samples": {"changed": [], "new": [], "deleted": []},
            "message": f"Sin cambios. No se creó una revisión nueva (última: #{latest_revision}).",
        }

    latest_files_result = await duplicacy_service.list_files(
        repo["path"],
        revision=latest_revision,
        password=password,
        storage_name=storage_name,
        extra_env=extra_env,
    )
    if latest_files_result.get("code") != 0:
        return {
            "ok": False,
            "createdRevision": latest_revision,
            "message": "No se pudo listar la revisión creada",
            "detail": latest_files_result.get("stdout") or latest_files_result.get("stderr") or "",
        }

    latest_map = _build_file_signature_map(latest_files_result.get("files") or [])
    prev_map: Dict[str, str] = {}
    if previous_revision is not None:
        prev_files_result = await duplicacy_service.list_files(
            repo["path"],
            revision=previous_revision,
            password=password,
            storage_name=storage_name,
            extra_env=extra_env,
        )
        if prev_files_result.get("code") == 0:
            prev_map = _build_file_signature_map(prev_files_result.get("files") or [])

    new_paths = sorted([p for p in latest_map.keys() if p not in prev_map])
    deleted_paths = sorted([p for p in prev_map.keys() if p not in latest_map])
    changed_paths = sorted([p for p in latest_map.keys() if p in prev_map and latest_map[p] != prev_map[p]])

    return {
        "ok": True,
        "createdRevision": latest_revision,
        "previousRevision": previous_revision,
        "fileCount": len(latest_map),
        "new": len(new_paths),
        "changed": len(changed_paths),
        "deleted": len(deleted_paths),
        "unchanged": (len(new_paths) + len(changed_paths) + len(deleted_paths)) == 0,
        "samples": {
            "new": _sample_paths(new_paths),
            "changed": _sample_paths(changed_paths),
            "deleted": _sample_paths(deleted_paths),
        },
    }


def get_storage_env(repo: Dict[str, Any], storage_name: Optional[str] = None) -> Dict[str, str]:
    target_name = storage_name or (get_primary_storage(repo) or {}).get("name")
    if not target_name:
        return {}

    storage = get_repo_storage(repo, target_name)
    if not storage:
        return {}

    if storage.get("type") != "wasabi":
        return {}

    secrets = (repo.get("_secrets") or {}).get(target_name, {})
    access_id = secrets.get("accessId")
    access_key = secrets.get("accessKey")
    if not access_id or not access_key:
        return {}

    return build_wasabi_env(access_id, access_key, target_name)


def build_wasabi_env(access_id: str, access_key: str, storage_name: str = "default") -> Dict[str, str]:
    access_id = (access_id or "").strip()
    access_key = (access_key or "").strip()
    if not access_id or not access_key:
        return {}
    upper = (storage_name or "default").upper()
    return {
        "DUPLICACY_S3_ID": access_id,
        "DUPLICACY_S3_SECRET": access_key,
        "DUPLICACY_WASABI_KEY": access_id,
        "DUPLICACY_WASABI_SECRET": access_key,
        f"DUPLICACY_{upper}_S3_ID": access_id,
        f"DUPLICACY_{upper}_S3_SECRET": access_key,
        f"DUPLICACY_{upper}_WASABI_KEY": access_id,
        f"DUPLICACY_{upper}_WASABI_SECRET": access_key,
    }


def get_storage_record_env(storage: Dict[str, Any], storage_name: str = "default") -> Dict[str, str]:
    if (storage.get("type") or "").lower() != "wasabi":
        return {}
    secrets = storage.get("_secrets") or {}
    return build_wasabi_env(secrets.get("accessId", ""), secrets.get("accessKey", ""), storage_name)


def build_wasabi_storage_url(region: str, endpoint: str, bucket: str, directory: Optional[str]) -> str:
    clean_endpoint = endpoint.strip().replace("https://", "").replace("http://", "").strip("/")
    clean_bucket = bucket.strip().strip("/")
    dir_part = (directory or "").strip().strip("/")
    base = f"wasabi://{region.strip()}@{clean_endpoint}/{clean_bucket}"
    return f"{base}/{dir_part}" if dir_part else base


def resolve_repo_destination(repo: RepoCreate) -> Dict[str, Any]:
    destination_type = (repo.destinationType or "").strip().lower()
    if not destination_type:
        destination_type = "wasabi" if repo.wasabiEnabled else "local"

    if destination_type not in {"local", "wasabi"}:
        raise HTTPException(status_code=400, detail="destinationType debe ser 'local' o 'wasabi'")

    if destination_type == "local":
        local_storage = (repo.localStoragePath or repo.storageUrl or "").strip()
        if not local_storage:
            raise HTTPException(status_code=400, detail="Falta el destino local (localStoragePath)")

        return {
            "destinationType": "local",
            "storageUrl": local_storage,
            "storage": {
                "name": "default",
                "type": "local",
                "label": "Local",
                "url": local_storage,
                "isDefault": True,
            },
            "extraEnv": {},
            "secrets": None,
        }

    required = {
        "wasabiEndpoint": repo.wasabiEndpoint,
        "wasabiRegion": repo.wasabiRegion,
        "wasabiBucket": repo.wasabiBucket,
        "wasabiAccessId": repo.wasabiAccessId,
        "wasabiAccessKey": repo.wasabiAccessKey,
    }
    missing = [k for k, v in required.items() if not (v or "").strip()]
    if missing:
        raise HTTPException(status_code=400, detail=f"Faltan campos de Wasabi: {', '.join(missing)}")

    wasabi_url = build_wasabi_storage_url(
        repo.wasabiRegion or "",
        repo.wasabiEndpoint or "",
        repo.wasabiBucket or "",
        repo.wasabiDirectory,
    )
    access_id = (repo.wasabiAccessId or "").strip()
    access_key = (repo.wasabiAccessKey or "").strip()

    return {
        "destinationType": "wasabi",
        "storageUrl": wasabi_url,
        "storage": {
            "name": "default",
            "type": "wasabi",
            "label": "Wasabi S3",
            "url": wasabi_url,
            "isDefault": True,
            "endpoint": (repo.wasabiEndpoint or "").strip(),
            "region": (repo.wasabiRegion or "").strip(),
            "bucket": (repo.wasabiBucket or "").strip(),
            "directory": (repo.wasabiDirectory or "").strip(),
        },
        "extraEnv": build_wasabi_env(access_id, access_key, "default"),
        "secrets": {
            "default": {
                "accessId": access_id,
                "accessKey": access_key,
            }
        },
    }


def infer_repo_destination_type(repo: Dict[str, Any]) -> str:
    primary = get_primary_storage(repo)
    if not primary:
        return "local"
    return "wasabi" if primary.get("type") == "wasabi" else "local"


def build_destination_from_update(existing_repo: Dict[str, Any], patch: RepoUpdate) -> Dict[str, Any]:
    current_storage = get_primary_storage(existing_repo) or {"type": "local", "url": existing_repo.get("storageUrl", "")}
    current_type = infer_repo_destination_type(existing_repo)
    destination_type = (patch.destinationType or current_type or "local").strip().lower()
    if destination_type not in {"local", "wasabi"}:
        raise HTTPException(status_code=400, detail="destinationType debe ser 'local' o 'wasabi'")

    if destination_type == "local":
        local_storage = (patch.localStoragePath or existing_repo.get("storageUrl") or current_storage.get("url") or "").strip()
        if not local_storage:
            raise HTTPException(status_code=400, detail="Falta el destino local")
        return {
            "destinationType": "local",
            "storageUrl": local_storage,
            "storages": [{
                "name": "default",
                "type": "local",
                "label": "Local",
                "url": local_storage,
                "isDefault": True,
            }],
            "secrets": None,
        }

    # wasabi
    primary = current_storage if current_storage.get("type") == "wasabi" else {}
    old_secrets = (existing_repo.get("_secrets") or {}).get("default", {})
    endpoint = (patch.wasabiEndpoint if patch.wasabiEndpoint is not None else primary.get("endpoint", "")).strip()
    region = (patch.wasabiRegion if patch.wasabiRegion is not None else primary.get("region", "")).strip()
    bucket = (patch.wasabiBucket if patch.wasabiBucket is not None else primary.get("bucket", "")).strip()
    directory = (patch.wasabiDirectory if patch.wasabiDirectory is not None else primary.get("directory", "")).strip()
    access_id = (patch.wasabiAccessId if patch.wasabiAccessId is not None else old_secrets.get("accessId", "")).strip()
    access_key = (patch.wasabiAccessKey if patch.wasabiAccessKey is not None else old_secrets.get("accessKey", "")).strip()

    required = {
        "wasabiEndpoint": endpoint,
        "wasabiRegion": region,
        "wasabiBucket": bucket,
        "wasabiAccessId": access_id,
        "wasabiAccessKey": access_key,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise HTTPException(status_code=400, detail=f"Faltan campos de Wasabi: {', '.join(missing)}")

    storage_url = build_wasabi_storage_url(region, endpoint, bucket, directory)
    return {
        "destinationType": "wasabi",
        "storageUrl": storage_url,
        "storages": [{
            "name": "default",
            "type": "wasabi",
            "label": "Wasabi S3",
            "url": storage_url,
            "isDefault": True,
            "endpoint": endpoint,
            "region": region,
            "bucket": bucket,
            "directory": directory,
        }],
        "secrets": {"default": {"accessId": access_id, "accessKey": access_key}},
    }


def build_destination_from_storage_ref(storage: Dict[str, Any]) -> Dict[str, Any]:
    storage_type = (storage.get("type") or "").strip().lower()
    if storage_type not in {"local", "wasabi"}:
        raise HTTPException(status_code=400, detail="Storage no soportado")

    base_storage = {
        "name": "default",
        "type": storage_type,
        "label": storage.get("label") or storage.get("name") or ("Wasabi S3" if storage_type == "wasabi" else "Local"),
        "url": storage.get("url") or storage.get("localPath") or "",
        "isDefault": True,
    }
    if storage_type == "wasabi":
        base_storage.update({
            "endpoint": storage.get("endpoint", ""),
            "region": storage.get("region", ""),
            "bucket": storage.get("bucket", ""),
            "directory": storage.get("directory", ""),
        })

    secrets = None
    if storage_type == "wasabi":
        sec = storage.get("_secrets") or {}
        if sec.get("accessId") and sec.get("accessKey"):
            secrets = {"default": {"accessId": sec["accessId"], "accessKey": sec["accessKey"]}}

    return {
        "destinationType": storage_type,
        "storageUrl": base_storage["url"],
        "storage": base_storage,
        "extraEnv": get_storage_record_env(storage, "default"),
        "secrets": secrets,
        "storageRefId": storage.get("id"),
        "storageDuplicacyPassword": ((storage.get("_secrets") or {}).get("duplicacyPassword") or None),
    }


def list_all_storages_for_ui() -> List[Dict[str, Any]]:
    explicit = config_store.storages.read()
    repos_data = config_store.repositories.read()

    by_key: Dict[str, Dict[str, Any]] = {}
    # explícitos primero
    for s in explicit:
        item = dict(s)
        item.setdefault("source", "managed")
        item.setdefault("linkedBackups", 0)
        item.setdefault("fromRepoIds", [])
        key = str(item.get("id") or f"url:{item.get('url')}")
        by_key[key] = item

    # derivados desde repos existentes (compatibilidad)
    for repo in repos_data:
        primary = get_primary_storage(repo)
        if not primary:
            continue
        url = primary.get("url") or repo.get("storageUrl")
        if not url:
            continue
        derived_key = f"derived:{primary.get('type') or 'legacy'}:{url}"
        if derived_key not in by_key:
            item = {
                "id": derived_key,
                "name": primary.get("label") or repo.get("name") or "Storage derivado",
                "type": primary.get("type") or "local",
                "label": primary.get("label") or ("Wasabi S3" if primary.get("type") == "wasabi" else "Local"),
                "url": url,
                "localPath": url if (primary.get("type") == "local") else None,
                "endpoint": primary.get("endpoint"),
                "region": primary.get("region"),
                "bucket": primary.get("bucket"),
                "directory": primary.get("directory"),
                "source": "legacy-repo",
                "linkedBackups": 0,
                "createdAt": repo.get("createdAt"),
                "fromRepoIds": [],
            }
            # traer secretos si existen en repo Wasabi
            repo_secrets = ((repo.get("_secrets") or {}).get(primary.get("name") or "default") or {})
            if repo_secrets:
                item["_secrets"] = {
                    "accessId": repo_secrets.get("accessId"),
                    "accessKey": repo_secrets.get("accessKey"),
                }
            by_key[derived_key] = item

        by_key[derived_key]["linkedBackups"] = int(by_key[derived_key].get("linkedBackups") or 0) + 1
        by_key[derived_key].setdefault("fromRepoIds", []).append(repo.get("id"))

    # enlazar backups también para explícitos por storageRefId / url
    for repo in repos_data:
        matched = None
        storage_ref_id = repo.get("storageRefId")
        if storage_ref_id:
            for k, s in by_key.items():
                if s.get("id") == storage_ref_id:
                    matched = s
                    break
        if not matched:
            primary = get_primary_storage(repo)
            repo_url = (primary or {}).get("url") or repo.get("storageUrl")
            if repo_url:
                for s in by_key.values():
                    if (s.get("url") or s.get("localPath")) == repo_url:
                        matched = s
                        break
        if matched:
            repo_id = repo.get("id")
            matched.setdefault("fromRepoIds", [])
            if repo_id and repo_id not in matched["fromRepoIds"]:
                matched["fromRepoIds"].append(repo_id)
                matched["linkedBackups"] = int(matched.get("linkedBackups") or 0) + 1

    result = list(by_key.values())
    result.sort(key=lambda s: ((s.get("source") != "managed"), str(s.get("name") or "").lower(), str(s.get("url") or "")))
    return result


def normalize_content_selection(selection: Optional[List[str]]) -> List[str]:
    if not selection:
        return []
    normalized: List[str] = []
    seen = set()
    for raw in selection:
        value = str(raw or "").strip().replace("\\", "/")
        if not value:
            continue
        value = value.lstrip("/")
        if not value or value in {".", "./"}:
            continue
        if ".." in value.split("/"):
            continue
        is_dir = value.endswith("/")
        value = value.rstrip("/")
        if not value:
            continue
        final_value = f"{value}/" if is_dir else value
        if final_value in seen:
            continue
        seen.add(final_value)
        normalized.append(final_value)
    return normalized


def build_duplicacy_filters_lines(selection: List[str]) -> List[str]:
    if not selection:
        return []

    include_lines: List[str] = []
    seen = set()

    def add_line(line: str):
        if line not in seen:
            seen.add(line)
            include_lines.append(line)

    for entry in selection:
        clean = entry.strip().replace("\\", "/")
        if not clean:
            continue
        is_dir = clean.endswith("/")
        trimmed = clean.rstrip("/")
        parts = [p for p in trimmed.split("/") if p]
        for i in range(1, len(parts)):
            parent = "/".join(parts[:i]) + "/"
            add_line(f"+{parent}")
        if is_dir:
            add_line(f"+{trimmed}/")
            add_line(f"+{trimmed}/*")
        else:
            add_line(f"+{trimmed}")

    return [
        "# Auto-generated by DupliManager",
        "# To backup everything again, clear contentSelection in the repo settings/UI",
        *include_lines,
        "-*",
    ]


def sync_repo_filters_file(repo: Dict[str, Any]) -> None:
    repo_path = Path(repo["path"])
    duplicacy_dir = repo_path / ".duplicacy"
    duplicacy_dir.mkdir(parents=True, exist_ok=True)
    filters_path = duplicacy_dir / "filters"

    selection = normalize_content_selection(repo.get("contentSelection"))
    if not selection:
        if filters_path.exists():
            try:
                text = filters_path.read_text(encoding="utf-8")
            except Exception:
                text = ""
            if "Auto-generated by DupliManager" in text:
                filters_path.unlink(missing_ok=True)
        return

    lines = build_duplicacy_filters_lines(selection)
    filters_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def list_local_directory_items(root_path: str, relative_path: str = "") -> Dict[str, Any]:
    root = Path(root_path).expanduser()
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=400, detail="La carpeta raíz no existe o no es válida")

    rel_norm = str(relative_path or "").replace("\\", "/").strip().strip("/")
    if rel_norm and ".." in rel_norm.split("/"):
        raise HTTPException(status_code=400, detail="Ruta relativa no válida")

    current = root / rel_norm if rel_norm else root
    try:
        current_resolved = current.resolve()
        root_resolved = root.resolve()
        current_resolved.relative_to(root_resolved)
    except Exception:
        raise HTTPException(status_code=400, detail="La ruta solicitada está fuera de la carpeta raíz")

    if not current.exists() or not current.is_dir():
        raise HTTPException(status_code=404, detail="La carpeta solicitada no existe")

    items: List[Dict[str, Any]] = []
    try:
        for child in current.iterdir():
            name = child.name
            if name in {".duplicacy"}:
                continue
            is_dir = child.is_dir()
            child_rel = child.relative_to(root).as_posix()
            rel_out = f"{child_rel}/" if is_dir else child_rel
            item: Dict[str, Any] = {
                "name": name,
                "isDir": is_dir,
                "relativePath": rel_out,
            }
            if not is_dir:
                try:
                    item["size"] = child.stat().st_size
                except Exception:
                    pass
            items.append(item)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Sin permisos para leer esa carpeta")

    items.sort(key=lambda x: (0 if x.get("isDir") else 1, x.get("name", "").lower()))
    return {
        "ok": True,
        "rootPath": str(root),
        "currentPath": (rel_norm + "/") if rel_norm else "",
        "items": items,
    }


async def ensure_restore_target_initialized(repo: Dict[str, Any], target_path: str, password: Optional[str], storage_name: Optional[str]) -> None:
    target = Path(target_path)
    target.mkdir(parents=True, exist_ok=True)
    duplicacy_dir = target / ".duplicacy"

    if duplicacy_dir.exists():
        raise HTTPException(
            status_code=400,
            detail=(
                f"La carpeta de restauración ya contiene .duplicacy ({duplicacy_dir}). "
                "DupliManager no reutiliza automáticamente esa configuración para evitar mezclar storages. "
                "Usa una carpeta sin .duplicacy o elimina/renombra esa carpeta .duplicacy."
            ),
        )

    primary = get_repo_storage(repo, storage_name or "default") or get_primary_storage(repo)
    if not primary:
        raise HTTPException(status_code=400, detail="Repositorio sin storage configurado")

    init_result = await duplicacy_service.init(
        str(target),
        repo["snapshotId"],
        primary["url"],
        password=password,
        encrypt=bool(repo.get("encrypted")),
        extra_env=get_storage_env(repo, storage_name or primary.get("name")),
    )
    if init_result["code"] != 0:
        raise HTTPException(
            status_code=500,
            detail=(
                init_result.get("stdout")
                or init_result.get("stderr")
                or "No se pudo inicializar la ruta de restauración"
            ),
        )


async def ensure_restore_target_initialized_from_storage(
    *,
    storage: Dict[str, Any],
    snapshot_id: str,
    target_path: str,
    password: Optional[str],
) -> None:
    target = Path(target_path)
    target.mkdir(parents=True, exist_ok=True)
    duplicacy_dir = target / ".duplicacy"
    if duplicacy_dir.exists():
        raise HTTPException(
            status_code=400,
            detail=(
                f"La carpeta de restauración ya contiene .duplicacy ({duplicacy_dir}) con otra configuración. "
                "Esto puede mezclar el storage actual con uno antiguo. "
                "Usa una carpeta sin .duplicacy o elimina/renombra esa carpeta .duplicacy antes de restaurar."
            ),
        )

    init_result = await duplicacy_service.init(
        str(target),
        snapshot_id,
        storage.get("url") or "",
        password=password,
        encrypt=bool(password),
        extra_env=get_storage_record_env(storage, "default"),
    )
    if init_result["code"] != 0:
        raise HTTPException(
            status_code=500,
            detail=(
                init_result.get("stdout")
                or init_result.get("stderr")
                or "No se pudo inicializar la ruta de restauración desde el storage"
            ),
        )


async def with_temp_storage_session_list_snapshots(
    *,
    storage: Dict[str, Any],
    snapshot_id: str,
    password: Optional[str],
) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="duplimanager-restore-probe-") as tmp_dir:
        init_result = await duplicacy_service.init(
            tmp_dir,
            snapshot_id,
            storage.get("url") or "",
            password=password,
            encrypt=bool(password),
            extra_env=get_storage_record_env(storage, "default"),
        )
        if init_result.get("code") != 0:
            raise HTTPException(status_code=400, detail=init_result.get("stdout") or init_result.get("stderr") or "No se pudo abrir el backup en el storage")
        return await duplicacy_service.list_snapshots(
            tmp_dir,
            password=password,
            storage_name="default",
            extra_env=get_storage_record_env(storage, "default"),
        )


async def with_temp_storage_session_list_files(
    *,
    storage: Dict[str, Any],
    snapshot_id: str,
    revision: int,
    password: Optional[str],
) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="duplimanager-restore-probe-") as tmp_dir:
        init_result = await duplicacy_service.init(
            tmp_dir,
            snapshot_id,
            storage.get("url") or "",
            password=password,
            encrypt=bool(password),
            extra_env=get_storage_record_env(storage, "default"),
        )
        if init_result.get("code") != 0:
            raise HTTPException(status_code=400, detail=init_result.get("stdout") or init_result.get("stderr") or "No se pudo abrir el backup en el storage")
        return await duplicacy_service.list_files(
            tmp_dir,
            revision=revision,
            password=password,
            storage_name="default",
            extra_env=get_storage_record_env(storage, "default"),
        )


def _aws_sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _aws_signature_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date = _aws_sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _aws_sign(k_date, region)
    k_service = _aws_sign(k_region, service)
    return _aws_sign(k_service, "aws4_request")


def _wasabi_signed_request(
    *,
    endpoint: str,
    region: str,
    access_id: str,
    access_key: str,
    method: str,
    canonical_uri: str,
    url: str,
    body: bytes = b"",
    timeout: int = 10,
) -> Any:
    service = "s3"
    host = endpoint
    canonical_querystring = ""
    t = datetime.now(timezone.utc)
    amz_date = t.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = t.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest()

    canonical_headers = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join([
        method,
        canonical_uri,
        canonical_querystring,
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join([
        algorithm,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    signing_key = _aws_signature_key(access_key, date_stamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization_header = (
        f"{algorithm} Credential={access_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    req = urllib_request.Request(url=url, data=(body if method in {"PUT", "POST"} else None), method=method)
    req.add_header("Host", host)
    req.add_header("x-amz-date", amz_date)
    req.add_header("x-amz-content-sha256", payload_hash)
    req.add_header("Authorization", authorization_header)
    if method in {"PUT", "POST"}:
        req.add_header("Content-Length", str(len(body)))
        req.add_header("Content-Type", "text/plain; charset=utf-8")
    return urllib_request.urlopen(req, timeout=timeout)


def test_wasabi_head_bucket(endpoint: str, region: str, bucket: str, access_id: str, access_key: str) -> Dict[str, Any]:
    clean_endpoint = endpoint.strip().replace("https://", "").replace("http://", "").strip("/")
    clean_region = (region or "").strip()
    clean_bucket = bucket.strip().strip("/")
    if not clean_endpoint or not clean_bucket or not clean_region:
        raise HTTPException(status_code=400, detail="Endpoint, región y bucket son obligatorios")
    if "wasabi" in clean_region.lower() or "." in clean_region:
        raise HTTPException(
            status_code=400,
            detail=f"La región de Wasabi parece incorrecta: '{clean_region}'. Usa algo como 'eu-central-1' (no el endpoint).",
        )

    url = f"https://{clean_endpoint}/{clean_bucket}"

    try:
        with _wasabi_signed_request(
            endpoint=clean_endpoint,
            region=region,
            access_id=access_id,
            access_key=access_key,
            method="HEAD",
            canonical_uri=f"/{clean_bucket}",
            url=url,
            body=b"",
            timeout=10,
        ) as resp:
            return {
                "ok": True,
                "status": getattr(resp, "status", 200),
                "bucket": clean_bucket,
                "endpoint": clean_endpoint,
                "requestId": resp.headers.get("x-amz-request-id") or resp.headers.get("x-wasabi-request-id"),
            }
    except urllib_error.HTTPError as exc:
        detail = f"Wasabi respondió HTTP {exc.code}"
        try:
            body = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        if exc.code == 403:
            detail = "Credenciales incorrectas o sin permisos sobre el bucket (HTTP 403)"
        elif exc.code == 404:
            detail = "Bucket no encontrado (HTTP 404)"
        elif exc.code == 400 and body:
            lowered = body.lower()
            if "authorizationheadermalformed" in lowered or "region" in lowered:
                detail = f"Región de Wasabi incorrecta ('{clean_region}'). Usa la región real del bucket (ej. eu-central-1)."
            elif "signature" in lowered:
                detail = "Firma inválida al conectar con Wasabi (revisa región, endpoint y credenciales)."
        raise HTTPException(status_code=400, detail=detail)
    except urllib_error.URLError as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo conectar al endpoint Wasabi: {exc.reason}")


def test_wasabi_write_bucket(endpoint: str, region: str, bucket: str, access_id: str, access_key: str) -> Dict[str, Any]:
    clean_endpoint = endpoint.strip().replace("https://", "").replace("http://", "").strip("/")
    clean_region = (region or "").strip()
    clean_bucket = bucket.strip().strip("/")
    if not clean_endpoint or not clean_bucket or not clean_region:
        raise HTTPException(status_code=400, detail="Endpoint, región y bucket son obligatorios")
    if "wasabi" in clean_region.lower() or "." in clean_region:
        raise HTTPException(
            status_code=400,
            detail=f"La región de Wasabi parece incorrecta: '{clean_region}'. Usa algo como 'eu-central-1' (no el endpoint).",
        )

    object_key = f"__duplimanager_probe__/{int(time.time())}-{uuid.uuid4().hex[:8]}.txt"
    object_body = f"DupliManager Wasabi write test {datetime.now().isoformat()}".encode("utf-8")
    encoded_key = quote(object_key, safe="/-_.~")
    url = f"https://{clean_endpoint}/{clean_bucket}/{encoded_key}"
    canonical_uri = f"/{clean_bucket}/{encoded_key}"

    try:
        with _wasabi_signed_request(
            endpoint=clean_endpoint,
            region=region,
            access_id=access_id,
            access_key=access_key,
            method="PUT",
            canonical_uri=canonical_uri,
            url=url,
            body=object_body,
            timeout=12,
        ) as resp_put:
            put_status = getattr(resp_put, "status", 200)

        with _wasabi_signed_request(
            endpoint=clean_endpoint,
            region=region,
            access_id=access_id,
            access_key=access_key,
            method="DELETE",
            canonical_uri=canonical_uri,
            url=url,
            body=b"",
            timeout=12,
        ) as resp_del:
            del_status = getattr(resp_del, "status", 204)

        return {
            "ok": True,
            "bucket": clean_bucket,
            "endpoint": clean_endpoint,
            "objectKey": object_key,
            "putStatus": put_status,
            "deleteStatus": del_status,
        }
    except urllib_error.HTTPError as exc:
        detail = f"Wasabi respondió HTTP {exc.code} en prueba de escritura"
        try:
            body = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        if exc.code == 403:
            detail = "Credenciales sin permisos de escritura/borrado en el bucket (HTTP 403)"
        elif exc.code == 404:
            detail = "Bucket no encontrado (HTTP 404)"
        elif exc.code == 400 and body:
            lowered = body.lower()
            if "authorizationheadermalformed" in lowered or "region" in lowered:
                detail = f"Región de Wasabi incorrecta ('{clean_region}'). Usa la región real del bucket (ej. eu-central-1)."
            elif "signature" in lowered:
                detail = "Firma inválida en prueba de escritura (revisa región, endpoint y credenciales)."
        raise HTTPException(status_code=400, detail=detail)
    except urllib_error.URLError as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo conectar al endpoint Wasabi: {exc.reason}")


def wasabi_object_exists(
    *,
    endpoint: str,
    region: str,
    bucket: str,
    access_id: str,
    access_key: str,
    object_key: str,
) -> bool:
    clean_endpoint = endpoint.strip().replace("https://", "").replace("http://", "").strip("/")
    clean_bucket = bucket.strip().strip("/")
    clean_key = (object_key or "").strip().strip("/")
    if not clean_endpoint or not clean_bucket or not clean_key:
        raise HTTPException(status_code=400, detail="Endpoint, bucket y object_key son obligatorios")

    encoded_key = quote(clean_key, safe="/-_.~")
    url = f"https://{clean_endpoint}/{clean_bucket}/{encoded_key}"
    canonical_uri = f"/{clean_bucket}/{encoded_key}"
    try:
        with _wasabi_signed_request(
            endpoint=clean_endpoint,
            region=region,
            access_id=access_id,
            access_key=access_key,
            method="HEAD",
            canonical_uri=canonical_uri,
            url=url,
            body=b"",
            timeout=10,
        ) as resp:
            _ = resp  # no-op; HEAD success means exists
            return True
    except urllib_error.HTTPError as exc:
        if exc.code == 404:
            return False
        if exc.code == 403:
            raise HTTPException(status_code=400, detail="Sin permisos para comprobar el config del storage Duplicacy (HTTP 403)")
        raise HTTPException(status_code=400, detail=f"Error comprobando config del storage Duplicacy (HTTP {exc.code})")
    except urllib_error.URLError as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo conectar al endpoint Wasabi: {exc.reason}")


async def validate_wasabi_duplicacy_storage_access_if_initialized(
    *,
    endpoint: str,
    region: str,
    bucket: str,
    directory: str,
    access_id: str,
    access_key: str,
    duplicacy_password: Optional[str],
) -> Dict[str, Any]:
    dir_part = (directory or "").strip().strip("/")
    config_key = f"{dir_part}/config" if dir_part else "config"
    has_config = wasabi_object_exists(
        endpoint=endpoint,
        region=region,
        bucket=bucket,
        access_id=access_id,
        access_key=access_key,
        object_key=config_key,
    )
    if not has_config:
        return {
            "checked": False,
            "initialized": False,
            "message": "No se detectó config de Duplicacy en ese bucket/directorio (storage vacío o no inicializado).",
        }

    req = WasabiSnapshotDetectRequest(
        endpoint=endpoint,
        region=region,
        bucket=bucket,
        directory=directory,
        accessId=access_id,
        accessKey=access_key,
        password=(duplicacy_password or None),
    )
    await detect_wasabi_snapshots(req)
    return {
        "checked": True,
        "initialized": True,
        "message": "Storage Duplicacy existente validado correctamente.",
    }

# ─── API ROUTES ───────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/system/pick-folder")
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


@app.get("/api/system/list-local-items")
def list_local_items(root: str, relative: Optional[str] = ""):
    return list_local_directory_items(root_path=root, relative_path=relative or "")


@app.post("/api/system/test-wasabi")
def test_wasabi_connection(req: WasabiConnectionTest):
    return test_wasabi_head_bucket(
        endpoint=req.endpoint,
        region=req.region,
        bucket=req.bucket,
        access_id=req.accessId,
        access_key=req.accessKey,
    )


@app.post("/api/system/test-wasabi-write")
def test_wasabi_write(req: WasabiConnectionTest):
    return test_wasabi_write_bucket(
        endpoint=req.endpoint,
        region=req.region,
        bucket=req.bucket,
        access_id=req.accessId,
        access_key=req.accessKey,
    )


@app.post("/api/system/detect-wasabi-snapshots")
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

# --- Storages ---

@app.get("/api/storages")
async def get_storages():
    return {"ok": True, "storages": [sanitize_storage(s) for s in list_all_storages_for_ui()]}


@app.post("/api/storages")
async def create_storage(req: StorageCreate):
    storage_type = (req.type or "").strip().lower()
    if storage_type not in {"local", "wasabi"}:
        raise HTTPException(status_code=400, detail="type debe ser 'local' o 'wasabi'")

    storages = config_store.storages.read()
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

    # Deduplicado simple por URL + tipo (actualiza alias/secretos si ya existe)
    existing = next((s for s in storages if s.get("type") == record.get("type") and (s.get("url") or s.get("localPath")) == (record.get("url") or record.get("localPath"))), None)
    if existing:
        existing["name"] = record["name"]
        existing["label"] = record["label"]
        if record.get("_secrets"):
            existing.setdefault("_secrets", {}).update(record["_secrets"])
        if storage_type == "wasabi":
            for key in ("endpoint", "region", "bucket", "directory", "url"):
                existing[key] = record.get(key)
        else:
            existing["localPath"] = record.get("localPath")
            existing["url"] = record.get("url")
        config_store.storages.write(storages)
        response = {"ok": True, "storage": sanitize_storage(existing), "updated": True}
        if storage_type == "wasabi" and 'validation' in locals() and not validation.get("checked"):
            response["warning"] = validation.get("message")
        return response

    storages.append(record)
    config_store.storages.write(storages)
    response = {"ok": True, "storage": sanitize_storage(record)}
    if storage_type == "wasabi" and 'validation' in locals() and not validation.get("checked"):
        response["warning"] = validation.get("message")
    return response


@app.put("/api/storages/{storage_id}")
async def update_storage(storage_id: str, req: StorageUpdate):
    storages = config_store.storages.read()
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
        config_store.storages.write(storages)
        return {"ok": True, "storage": sanitize_storage(target)}

    if storage_type != "wasabi":
        raise HTTPException(status_code=400, detail="Tipo de storage no soportado para edición")

    # Wasabi fields (blank => keep current)
    endpoint = (req.endpoint or "").strip() if req.endpoint is not None else (target.get("endpoint") or "")
    region = (req.region or "").strip() if req.region is not None else (target.get("region") or "")
    bucket = (req.bucket or "").strip() if req.bucket is not None else (target.get("bucket") or "")
    directory = (req.directory or "").strip() if req.directory is not None else (target.get("directory") or "")
    secrets = target.setdefault("_secrets", {})
    access_id = (req.accessId or "").strip() if req.accessId is not None and (req.accessId or "").strip() else (secrets.get("accessId") or "")
    access_key = (req.accessKey or "").strip() if req.accessKey is not None and (req.accessKey or "").strip() else (secrets.get("accessKey") or "")

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
        effective_dup_pwd = (secrets.get("duplicacyPassword") or None)
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

    config_store.storages.write(storages)
    response = {"ok": True, "storage": sanitize_storage(target)}
    if not validation.get("checked"):
        response["warning"] = validation.get("message")
    return response


@app.delete("/api/storages/{storage_id}")
async def delete_storage(storage_id: str):
    storages = config_store.storages.read()
    target = next((s for s in storages if s.get("id") == storage_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Storage no encontrado")
    storages = [s for s in storages if s.get("id") != storage_id]
    config_store.storages.write(storages)
    return {"ok": True, "removed": sanitize_storage(target)}


@app.get("/api/storages/{storage_id}/snapshots")
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
        accessId=((storage.get("_secrets") or {}).get("accessId") or ""),
        accessKey=((storage.get("_secrets") or {}).get("accessKey") or ""),
        password=((storage.get("_secrets") or {}).get("duplicacyPassword") or None),
    )
    return await detect_wasabi_snapshots(req)


@app.get("/api/storages/{storage_id}/snapshot-revisions")
async def list_storage_snapshot_revisions(storage_id: str, snapshot_id: str, password: Optional[str] = None):
    storage = get_storage_by_id(storage_id)
    if not storage:
        raise HTTPException(status_code=404, detail="Storage no encontrado")
    snapshot_id = (snapshot_id or "").strip()
    if not snapshot_id:
        raise HTTPException(status_code=400, detail="snapshot_id es obligatorio")
    effective_password = (password or "").strip() or ((storage.get("_secrets") or {}).get("duplicacyPassword") or None)
    cache_key = _remote_cache_key(
        "storage-revisions",
        storage_id,
        snapshot_id,
        bool(effective_password),
        hashlib.sha256((effective_password or "").encode("utf-8")).hexdigest() if effective_password else "",
    )
    cached = _remote_cache_get(cache_key)
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


@app.get("/api/storages/{storage_id}/snapshot-files")
async def list_storage_snapshot_files(storage_id: str, snapshot_id: str, revision: int, password: Optional[str] = None):
    storage = get_storage_by_id(storage_id)
    if not storage:
        raise HTTPException(status_code=404, detail="Storage no encontrado")
    snapshot_id = (snapshot_id or "").strip()
    if not snapshot_id:
        raise HTTPException(status_code=400, detail="snapshot_id es obligatorio")
    effective_password = (password or "").strip() or ((storage.get("_secrets") or {}).get("duplicacyPassword") or None)
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


@app.post("/api/storages/{storage_id}/restore")
async def restore_from_storage(storage_id: str, req: StorageRestoreRequest):
    if storage_id != req.storageId:
        raise HTTPException(status_code=400, detail="storageId de la URL y del body no coinciden")
    storage = get_storage_by_id(storage_id)
    if not storage:
        raise HTTPException(status_code=404, detail="Storage no encontrado")
    snapshot_id = (req.snapshotId or "").strip()
    if not snapshot_id:
        raise HTTPException(status_code=400, detail="snapshotId es obligatorio")
    restore_path = (req.restorePath or "").strip()
    if not restore_path:
        raise HTTPException(status_code=400, detail="Para restaurar desde un storage sin backup local debes indicar una ruta de restauración")

    effective_password = (req.password or "").strip() or ((storage.get("_secrets") or {}).get("duplicacyPassword") or None)
    started_monotonic = time.monotonic()
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
    )
    if result["code"] != 0:
        duration = round(time.monotonic() - started_monotonic, 2)
        logger.error(
            "[Restore] Fin storage=%s snapshotId=%s revision=%s resultado=ERROR codigo=%s duracion_s=%s",
            storage.get("name") or storage_id,
            snapshot_id,
            req.revision,
            result.get("code"),
            duration,
        )
        raise HTTPException(status_code=500, detail=result.get("stdout") or result.get("stderr") or "Restore failed")

    duration = round(time.monotonic() - started_monotonic, 2)
    logger.info(
        "[Restore] Fin storage=%s snapshotId=%s revision=%s resultado=OK codigo=%s duracion_s=%s destino_real=%s",
        storage.get("name") or storage_id,
        snapshot_id,
        req.revision,
        result.get("code"),
        duration,
        restore_path,
    )
    return {"ok": True, "output": result.get("stdout", ""), "restorePath": restore_path}

# --- Repositories / Backup Jobs ---

@app.get("/api/repos")
async def get_repos():
    repos = config_store.repositories.read()
    return {"ok": True, "repos": [sanitize_repo(r) for r in repos]}


@app.get("/api/repos/{repo_id}")
async def get_repo(repo_id: str):
    repos_data = config_store.repositories.read()
    repo = next((r for r in repos_data if r["id"] == repo_id), None)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return {"ok": True, "repo": sanitize_repo(repo)}

@app.post("/api/repos")
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

    init_password = repo.password or (destination.get("storageDuplicacyPassword") if destination else None)
    encrypt_enabled = repo.encrypt if repo.encrypt is not None else (True if init_password else False)

    result = await duplicacy_service.init(
        str(repo_path), 
        repo.snapshotId, 
        destination["storageUrl"],
        password=init_password,
        encrypt=encrypt_enabled,
        extra_env=destination.get("extraEnv")
    )

    if result["code"] != 0:
        detail = (result.get("stdout") or result.get("stderr") or "Duplicacy init failed")
        if "EmptyStaticCreds" in detail or "Enter Wasabi key" in detail:
            detail = (
                "Duplicacy no recibió las credenciales de Wasabi (key/secret) en el init. "
                "Verifica Access ID / Access Key. "
                f"Detalle: {detail}"
            )
        elif "likely to have been initialized with a password before" in detail:
            detail = (
                "Ese storage de Duplicacy parece estar cifrado con una contraseña previa. "
                "Usa 'Importar repositorio existente (Wasabi)' y escribe la contraseña de Duplicacy correcta. "
                f"Detalle: {detail}"
            )
        raise HTTPException(status_code=500, detail=detail)

    storages = [destination["storage"]]
    secrets: Dict[str, Dict[str, str]] = destination.get("secrets") or {}

    repos_data = config_store.repositories.read()
    new_repo = {
        "id": str(uuid.uuid4()),
        "name": repo.name,
        "path": str(repo_path),
        "snapshotId": repo.snapshotId,
        "storageUrl": destination["storageUrl"],  # legacy compatibility
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
    config_store.repositories.write(repos_data)
    
    return {"ok": True, "repo": sanitize_repo(new_repo)}


@app.put("/api/repos/{repo_id}")
async def update_repo(repo_id: str, req: RepoUpdate):
    repos_data = config_store.repositories.read()
    idx = next((i for i, r in enumerate(repos_data) if r["id"] == repo_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo = dict(repos_data[idx])
    changed_destination = False

    if req.name is not None:
        repo["name"] = req.name.strip() or repo.get("name")
    if req.path is not None:
        repo["path"] = req.path.strip() or repo.get("path")
    if req.snapshotId is not None:
        repo["snapshotId"] = req.snapshotId.strip() or repo.get("snapshotId")
    if req.contentSelection is not None:
        repo["contentSelection"] = normalize_content_selection(req.contentSelection)
    if req.schedule is not None:
        repo["schedule"] = normalize_schedule_config(req.schedule, repo.get("schedule"))

    destination_fields_used = any([
        req.destinationType is not None,
        req.localStoragePath is not None,
        req.wasabiEndpoint is not None,
        req.wasabiRegion is not None,
        req.wasabiBucket is not None,
        req.wasabiDirectory is not None,
        req.wasabiAccessId is not None,
        req.wasabiAccessKey is not None,
    ])
    if destination_fields_used:
        destination = build_destination_from_update(repo, req)
        repo["storageUrl"] = destination["storageUrl"]
        repo["storages"] = destination["storages"]
        if destination["secrets"]:
            repo["_secrets"] = destination["secrets"]
        else:
            repo.pop("_secrets", None)
        changed_destination = True

    repos_data[idx] = repo
    config_store.repositories.write(repos_data)

    response: Dict[str, Any] = {"ok": True, "repo": sanitize_repo(repo)}
    if changed_destination:
        response["warning"] = (
            "Se actualizó la configuración en DupliManager. "
            "Si el repositorio ya estaba inicializado, la configuración interna de Duplicacy (.duplicacy) puede requerir reconfiguración manual."
        )
    return response

@app.delete("/api/repos/{repo_id}")
async def delete_repo(repo_id: str):
    repos_data = config_store.repositories.read()
    repo = next((r for r in repos_data if r["id"] == repo_id), None)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    repos_data = [r for r in repos_data if r["id"] != repo_id]
    config_store.repositories.write(repos_data)
    return {"ok": True, "removed": sanitize_repo(repo)}

# --- Backup ---

@app.post("/api/backup/start")
async def start_backup(req: BackupStart):
    repos_data = config_store.repositories.read()
    repo = next((r for r in repos_data if r["id"] == req.repoId), None)
    
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if req.repoId in active_backups:
        raise HTTPException(status_code=409, detail="Backup already running")

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
                primary_storage_name = primary.get("name")
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
                        storage_name=primary.get("name"),
                        extra_env=get_storage_env(repo, primary.get("name"))
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
            all_repos = config_store.repositories.read()
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
            config_store.repositories.write(all_repos)
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
            active_backup_processes.pop(req.repoId, None)
            active_backups.pop(req.repoId, None)

    asyncio.create_task(run_backup_task())
    return {"ok": True}

@app.get("/api/backup/status/{repo_id}")
async def get_backup_status(repo_id: str):
    info = active_backups.get(repo_id)
    if not info:
        return {"ok": True, "running": False}
    return {"ok": True, "running": True, **info}


@app.post("/api/backup/cancel")
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

@app.get("/api/backup/progress/{repo_id}")
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

# --- Snapshots & Restore ---

@app.get("/api/snapshots/{repo_id}")
async def list_snapshots(repo_id: str, password: Optional[str] = None, storage: Optional[str] = None):
    repos_data = config_store.repositories.read()
    repo = next((r for r in repos_data if r["id"] == repo_id), None)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    storage_name = storage or (get_primary_storage(repo) or {}).get("name")
    result = await duplicacy_service.list_snapshots(
        repo["path"],
        password=password,
        storage_name=storage_name,
        extra_env=get_storage_env(repo, storage_name)
    )
    return {"ok": True, "snapshots": result["snapshots"]}


@app.get("/api/snapshots/{repo_id}/files")
async def list_snapshot_files(repo_id: str, revision: int, password: Optional[str] = None, storage: Optional[str] = None):
    repos_data = config_store.repositories.read()
    repo = next((r for r in repos_data if r["id"] == repo_id), None)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    storage_name = storage or (get_primary_storage(repo) or {}).get("name")
    result = await duplicacy_service.list_files(
        repo["path"],
        revision=revision,
        password=password,
        storage_name=storage_name,
        extra_env=get_storage_env(repo, storage_name),
    )
    if result["code"] != 0:
        raise HTTPException(status_code=500, detail=result.get("stdout") or result.get("stderr") or "No se pudo listar archivos")
    return {"ok": True, "files": result["files"]}

@app.post("/api/restore")
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
    if restore_path and os.path.normcase(os.path.abspath(restore_path)) != os.path.normcase(os.path.abspath(repo["path"])):
        await ensure_restore_target_initialized(repo, restore_path, req.password, storage_name)
        working_path = restore_path

    result = await duplicacy_service.restore(
        working_path, 
        req.revision, 
        overwrite=req.overwrite, 
        password=req.password,
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
        result.get("code"),
        duration,
        working_path,
    )
    return {"ok": True, "output": result["stdout"], "restorePath": working_path}

# --- Config & Logs ---

@app.get("/api/config/settings")
async def get_settings():
    s = config_store.settings.read()
    if "duplicacyPath" not in s and "duplicacy_path" in s:
        s["duplicacyPath"] = s.get("duplicacy_path")
    return {"ok": True, "settings": s}

@app.put("/api/config/settings")
async def update_settings(req: Request):
    data = await req.json()
    if "duplicacyPath" in data and "duplicacy_path" not in data:
        data["duplicacy_path"] = data["duplicacyPath"]
    if "duplicacy_path" in data and "duplicacyPath" not in data:
        data["duplicacyPath"] = data["duplicacy_path"]
    current = config_store.settings.read()
    current.update(data)
    config_store.settings.write(current)
    return {"ok": True, "settings": current}

@app.get("/api/config/logs")
async def list_logs():
    return {"ok": True, "files": get_log_files()}

@app.get("/api/config/logs/{filename}")
async def read_log(filename: str):
    content = read_log_file(filename)
    if content is None:
        raise HTTPException(status_code=404, detail="Log file not found")
    return {"ok": True, "content": content}


@app.on_event("startup")
async def on_startup():
    global scheduler_task
    if scheduler_task is None or scheduler_task.done():
        scheduler_task = asyncio.create_task(scheduler_loop())


@app.on_event("shutdown")
async def on_shutdown():
    global scheduler_task
    if scheduler_task and not scheduler_task.done():
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
    scheduler_task = None

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
