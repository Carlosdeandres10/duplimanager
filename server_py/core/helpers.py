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
from fastapi import HTTPException
from pydantic import BaseModel

from server_py.utils.logger import get_logger, get_log_files, read_log_file
from server_py.utils import config_store
from server_py.services.duplicacy import service as duplicacy_service
from server_py.core.remote_cache import (
    REMOTE_LIST_CACHE_TTL_SECONDS,
    CACHE_DIR,
    PROBES_DIR,
    LOOKUP_CACHE_FILE,
    remote_storage_list_cache,
    _remote_cache_key,
    _remote_cache_get,
    _remote_cache_set,
)
from server_py.models.schemas import (
    RepoCreate, BackupStart, BackupCancelRequest, RestoreRequest, StorageRestoreRequest,
    WasabiConnectionTest, WasabiSnapshotDetectRequest, RepoUpdate, StorageCreate, StorageUpdate
)
from .storage_helpers import (sanitize_storage, get_storage_by_id, get_repo_storage, get_primary_storage, describe_storage, get_storage_env, get_repo_duplicacy_password, build_wasabi_env, get_storage_record_env, build_wasabi_storage_url, resolve_repo_destination, infer_repo_destination_type, build_destination_from_update, build_destination_from_storage_ref, list_all_storages_for_ui)

logger = get_logger("Helpers")

# ─── STATE ────────────────────────────────────────────────
active_backups: Dict[str, Dict[str, Any]] = {}
completed_backups: Dict[str, Dict[str, Any]] = {}
active_backup_processes: Dict[str, Any] = {}
scheduler_task: Optional[asyncio.Task] = None
scheduler_running: bool = False
FIXED_DUPLICACY_THREADS = 16

INTERNAL_SECRET_KEYS = {"_secrets", "wasabiAccessKey", "wasabiAccessId"}
INTERNAL_STORAGE_SECRET_KEYS = {"_secrets", "accessId", "accessKey", "duplicacyPassword"}


def sanitize_repo(repo: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(repo)
    for key in INTERNAL_SECRET_KEYS:
        sanitized.pop(key, None)
    return sanitized










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
    from server_py.routers.backups import start_backup
    
    repos_data = config_store.repositories.read()
    now = datetime.now()

    for repo in repos_data:
        repo_id = repo.get("id")
        schedule = repo.get("schedule")
        
        if not isinstance(schedule, dict) or not schedule.get("enabled"):
            continue
            
        next_run = _parse_iso_datetime(schedule.get("nextRunAt"))
        if next_run is None:
            # Inicialización de primera ejecución
            def init_next_run(all_repos):
                for r in all_repos:
                    if r["id"] == repo_id:
                        r_sch = r.get("schedule")
                        if r_sch and r_sch.get("enabled"):
                            new_next = compute_next_run_for_schedule(r_sch, now)
                            r_sch["nextRunAt"] = new_next.isoformat() if new_next else None
                return all_repos
            config_store.repositories.atomic_update(init_next_run)
            continue

        if repo_id in active_backups:
            continue
            
        if now >= next_run:
            # Toca ejecutar
            threads = schedule.get("threads")
            logger.info("[Scheduler] Toca backup repo=%s nombre=%s", repo_id, repo.get("name"))
            
            # 1. Actualizar el schedule atómicamente ANTES de lanzar para evitar re-disparos
            def mark_queued(all_repos):
                for r in all_repos:
                    if r["id"] == repo_id:
                        r_sch = r.get("schedule")
                        r_sch["lastRunAt"] = now.isoformat()
                        r_sch["lastRunStatus"] = "queued"
                        r_sch["lastError"] = None
                        # Calcular próxima ejecución (después de esta)
                        new_next = compute_next_run_for_schedule(r_sch, now + timedelta(seconds=1))
                        r_sch["nextRunAt"] = new_next.isoformat() if new_next else None
                return all_repos
            config_store.repositories.atomic_update(mark_queued)
            
            # 2. Lanzar el backup (async)
            try:
                await start_backup(BackupStart(repoId=repo_id, threads=threads, trigger="scheduler"))
            except Exception as e:
                logger.error(f"[Scheduler] Fallo al iniciar backup repo={repo_id}: {e}")
                def mark_error(all_repos):
                    for r in all_repos:
                        if r["id"] == repo_id:
                            r_sch = r.get("schedule")
                            r_sch["lastRunStatus"] = "error"
                            r_sch["lastError"] = str(e)
                    return all_repos
                config_store.repositories.atomic_update(mark_error)



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


def _get_probe_dir(storage_id: str, snapshot_id: str) -> str:
    safe_storage = "".join(c if c.isalnum() else "_" for c in storage_id)
    safe_snapshot = "".join(c if c.isalnum() else "_" for c in snapshot_id)
    probe_dir = PROBES_DIR / f"{safe_storage}_{safe_snapshot}"
    probe_dir.mkdir(parents=True, exist_ok=True)
    return str(probe_dir)


async def with_temp_storage_session_list_snapshots(
    *,
    storage: Dict[str, Any],
    snapshot_id: str,
    password: Optional[str],
) -> Dict[str, Any]:
    probe_dir_path = _get_probe_dir(storage.get("id") or "unknown", snapshot_id)
    pref_file = Path(probe_dir_path) / ".duplicacy" / "preferences"
    
    if not pref_file.exists():
        init_result = await duplicacy_service.init(
            probe_dir_path,
            snapshot_id,
            storage.get("url") or "",
            password=password,
            encrypt=bool(password),
            extra_env=get_storage_record_env(storage, "default"),
        )
        if init_result.get("code") != 0:
            raise HTTPException(status_code=400, detail=init_result.get("stdout") or init_result.get("stderr") or "No se pudo abrir el backup en el storage")
            
    return await duplicacy_service.list_snapshots(
        probe_dir_path,
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
    probe_dir_path = _get_probe_dir(storage.get("id") or "unknown", snapshot_id)
    pref_file = Path(probe_dir_path) / ".duplicacy" / "preferences"
    
    if not pref_file.exists():
        init_result = await duplicacy_service.init(
            probe_dir_path,
            snapshot_id,
            storage.get("url") or "",
            password=password,
            encrypt=bool(password),
            extra_env=get_storage_record_env(storage, "default"),
        )
        if init_result.get("code") != 0:
            raise HTTPException(status_code=400, detail=init_result.get("stdout") or init_result.get("stderr") or "No se pudo abrir el backup en el storage")
            
    return await duplicacy_service.list_files(
        probe_dir_path,
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
    await do_detect_wasabi_snapshots(req)
    return {
        "checked": True,
        "initialized": True,
        "message": "Storage Duplicacy existente validado correctamente.",
    }


async def do_detect_wasabi_snapshots(req):
    from server_py.models.schemas import WasabiSnapshotDetectRequest
    storage_url = build_wasabi_storage_url(req.region, req.endpoint, req.bucket, req.directory)
    # Importante: Duplicacy usa la región como alias en la URL, así que el env debe coincidir
    extra_env = build_wasabi_env(req.accessId, req.accessKey, req.region)

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
            from fastapi import HTTPException
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


            from fastapi import HTTPException
            detail = (list_result.get("stdout") or list_result.get("stderr") or "No se pudieron listar snapshots")
            raise HTTPException(status_code=400, detail=detail)

        snapshots = list_result.get("snapshots") or []
        grouped = {}
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
