import os
import uuid
import tempfile
import asyncio
import hashlib
import json
import re
import urllib.request
import urllib.error
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from server_py.utils.config_store import settings as settings_config
from server_py.utils.logger import get_log_files, read_log_file, get_logger
from server_py.utils.paths import runtime_paths_info
from server_py.utils.secret_crypto import protect_secret, reveal_secret
from server_py.models.schemas import WasabiConnectionTest, WasabiSnapshotDetectRequest
from server_py.services.duplicacy import service as duplicacy_service
from server_py.services.notifications import test_backup_notifications
from server_py.services.secrets_migration import migrate_all_secrets_in_config
from server_py.services.panel_auth import (
    get_public_status as get_panel_auth_public_status,
    verify_panel_password,
    create_session,
    revoke_session,
    is_session_valid,
    save_panel_access,
    get_session_ttl_seconds,
    should_use_secure_cookie,
    get_login_lockout_status,
    register_login_failure,
    clear_login_failures,
    SESSION_COOKIE_NAME,
)
from server_py.core.helpers import (
    list_local_directory_items, test_wasabi_head_bucket, test_wasabi_write_bucket,
    build_wasabi_storage_url, build_wasabi_env, _remote_cache_key, _remote_cache_get, _remote_cache_set,
    scheduler_loop, scheduler_task
)


router = APIRouter(tags=["system"])
logger = get_logger("SystemRouter")
APP_VERSION = (os.getenv("DUPLIMANAGER_VERSION") or "1.0.0").strip() or "1.0.0"

LOG_LINE_RE = re.compile(r"^\[([^\]]+)\]\s+\[([^\]]+)\]\s+\[([^\]]+)\]\s*(.*)$")


def _client_ip(request: Optional[Request]) -> str:
    try:
        return (((request.client if request else None) and request.client.host) or "unknown").strip() or "unknown"
    except Exception:
        return "unknown"


def _auth_audit(request: Optional[Request], event: str, *, level: str = "info", **fields: Any) -> None:
    safe_fields: Dict[str, Any] = {}
    for key, value in (fields or {}).items():
        if value is None:
            continue
        if isinstance(value, str):
            safe_fields[key] = value.replace("\n", " ").replace("\r", " ").strip()
        else:
            safe_fields[key] = value
    safe_fields["ip"] = _client_ip(request)
    try:
        ua = str((request.headers.get("user-agent") if request else "") or "").strip()
    except Exception:
        ua = ""
    if ua:
        safe_fields["ua"] = (ua[:180] + "…") if len(ua) > 180 else ua
    payload = " ".join(f"{k}={safe_fields[k]}" for k in sorted(safe_fields.keys()))
    msg = f"[AuthAudit] event={event}"
    if payload:
        msg += f" {payload}"
    if level == "warning":
        logger.warning(msg)
    elif level == "error":
        logger.error(msg)
    else:
        logger.info(msg)


def _parse_log_datetime(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _normalize_log_op_type(source: str, message: str) -> Optional[str]:
    source_l = (source or "").lower()
    msg = message or ""
    if re.search(r"\[Backup\]", msg, re.IGNORECASE):
        return "backup"
    if re.search(r"\[Restore\]", msg, re.IGNORECASE):
        return "restore"
    if re.search(r"\[Storage\]", msg, re.IGNORECASE) or re.search(r"\bstorage\b", msg, re.IGNORECASE):
        return "storage"
    if re.search(r"\[Scheduler\]", msg, re.IGNORECASE):
        return "scheduler"
    if source_l == "duplicacycli":
        return "duplicacy"
    return None


def _parse_log_line(raw_line: str) -> Dict[str, Any]:
    raw = str(raw_line or "")
    m = LOG_LINE_RE.match(raw)
    if not m:
        return {
            "raw": raw,
            "time": "",
            "timeIso": None,
            "dt": None,
            "level": "OTHER",
            "source": "",
            "message": raw,
            "opType": None,
        }
    time_str = m.group(1) or ""
    level = (m.group(2) or "").upper() or "OTHER"
    source = m.group(3) or ""
    message = m.group(4) or ""
    dt = _parse_log_datetime(time_str)
    return {
        "raw": raw,
        "time": time_str,
        "timeIso": dt.isoformat() if dt else None,
        "dt": dt,
        "level": level,
        "source": source,
        "message": message,
        "opType": _normalize_log_op_type(source, message),
    }


def _parse_filter_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _apply_log_filters(
    rows: List[Dict[str, Any]],
    *,
    level: Optional[str] = None,
    op_type: Optional[str] = None,
    text: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[Dict[str, Any]]:
    lvl = (level or "").strip().upper()
    op = (op_type or "").strip().lower()
    q = (text or "").strip().lower()
    dt_from = _parse_filter_dt(date_from)
    dt_to = _parse_filter_dt(date_to)
    if dt_to and len(str(date_to or "").strip()) <= 10:
        # Inclusive whole day if only date is provided
        dt_to = dt_to.replace(hour=23, minute=59, second=59)

    out: List[Dict[str, Any]] = []
    for row in rows:
        if lvl and (row.get("level") or "OTHER").upper() != lvl:
            continue
        if op and (row.get("opType") or "").lower() != op:
            continue
        row_dt = row.get("dt")
        if dt_from and row_dt and row_dt < dt_from:
            continue
        if dt_from and not row_dt:
            continue
        if dt_to and row_dt and row_dt > dt_to:
            continue
        if dt_to and not row_dt:
            continue
        if q:
            haystack = f"{row.get('time','')} {row.get('level','')} {row.get('source','')} {row.get('message','')} {row.get('raw','')}".lower()
            if q not in haystack:
                continue
        out.append(row)
    return out


def _log_counts(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    levels = {"INFO": 0, "WARNING": 0, "ERROR": 0, "DEBUG": 0, "OTHER": 0}
    types = {"backup": 0, "restore": 0, "storage": 0, "scheduler": 0, "duplicacy": 0}
    for r in rows:
        lvl = (r.get("level") or "OTHER").upper()
        levels[lvl] = levels.get(lvl, 0) + 1
        op = (r.get("opType") or "").lower()
        if op:
            types[op] = types.get(op, 0) + 1
    return {"levels": levels, "types": types}


def _parse_semverish(value: str) -> Optional[List[int]]:
    s = str(value or "").strip()
    if not s:
        return None
    if s.lower().startswith("v"):
        s = s[1:]
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", s)
    if not m:
        return None
    return [int(m.group(1)), int(m.group(2)), int(m.group(3))]


def _is_version_newer(latest: str, current: str) -> bool:
    a = _parse_semverish(latest)
    b = _parse_semverish(current)
    if not a or not b:
        return False
    return tuple(a) > tuple(b)


def _fetch_json_url(url: str, timeout_seconds: float = 4.0) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"DupliManager/{APP_VERSION} (update-check)"},
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("latest.json debe ser un objeto JSON")
    return data

# ─── API ROUTES ───────────────────────────────────────────

@router.get("/api/health")
async def health():
    return {
        "ok": True,
        "version": APP_VERSION,
        "timestamp": datetime.now().isoformat()
    }


@router.get("/api/system/pick-folder")
def pick_folder(start: Optional[str] = None):
    import sys

    if getattr(sys, "frozen", False):
        raise HTTPException(
            status_code=400,
            detail="El selector visual de carpetas no está disponible en la versión servidor. Escribe la ruta a mano.",
        )
    try:
        import tkinter as tk
        from tkinter import filedialog
    except HTTPException:
        raise
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


@router.post("/api/system/test-notification-channels")
async def test_notification_channels(request: Request):
    body = await request.json()
    channel = str((body or {}).get("channel") or "both").strip().lower()
    test_keyword = str((body or {}).get("keyword") or "").strip()

    payload = {
        "repoName": "Prueba configuración global",
        "snapshotId": "test-global",
        "trigger": "manual",
        "sourcePath": "—",
        "targetLabel": "—",
        "finishedAt": datetime.now().isoformat(),
        "durationSeconds": 0,
        "backupSummary": {"ok": True, "message": "Prueba manual desde Configuración"},
        "backupLog": "Prueba manual de canales globales desde Configuración.",
    }

    repo_notifications: Dict[str, Any] = {"healthchecks": {}, "email": {}}
    if test_keyword:
        repo_notifications["healthchecks"]["successKeyword"] = test_keyword

    if channel == "healthchecks":
        repo_notifications["healthchecks"]["enabled"] = True
        repo_notifications["email"]["enabled"] = False
    elif channel == "email":
        repo_notifications["healthchecks"]["enabled"] = False
        repo_notifications["email"]["enabled"] = True
    else:
        repo_notifications["healthchecks"]["enabled"] = True
        repo_notifications["email"]["enabled"] = True
    result = await test_backup_notifications(payload, repo_notifications)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("detail") or "Falló la prueba de notificación")
    return result


@router.get("/api/auth/status")
async def auth_status(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    status = get_panel_auth_public_status()
    status["authenticated"] = bool(status.get("requiresAuth")) and is_session_valid(token)
    if not status.get("requiresAuth"):
        status["authenticated"] = True
    return {"ok": True, "auth": status}


@router.post("/api/auth/login")
async def auth_login(request: Request, response: Response):
    body = await request.json()
    password = str((body or {}).get("password") or "")
    status = get_panel_auth_public_status()
    client_key = ((request.client and request.client.host) or "unknown").strip() or "unknown"
    if status.get("requiresAuth"):
        lockout = get_login_lockout_status(client_key)
        if not lockout.get("allowed"):
            retry_after = int(lockout.get("retryAfterSeconds") or 60)
            _auth_audit(request, "login_blocked", level="warning", retryAfterSeconds=retry_after)
            raise HTTPException(
                status_code=429,
                detail=f"Demasiados intentos fallidos. Intenta de nuevo en {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )
        if not verify_panel_password(password):
            failure = register_login_failure(client_key)
            if failure.get("blocked"):
                retry_after = int(failure.get("retryAfterSeconds") or 60)
                _auth_audit(
                    request,
                    "login_blocked",
                    level="warning",
                    retryAfterSeconds=retry_after,
                    failedCount=int(failure.get("count") or 0),
                )
                raise HTTPException(
                    status_code=429,
                    detail=f"Demasiados intentos fallidos. Intenta de nuevo en {retry_after}s.",
                    headers={"Retry-After": str(retry_after)},
                )
            _auth_audit(
                request,
                "login_failed",
                level="warning",
                failedCount=int(failure.get("count") or 0),
            )
            raise HTTPException(status_code=401, detail="Contraseña incorrecta")
        clear_login_failures(client_key)
    token = create_session()
    session_ttl = get_session_ttl_seconds()
    secure_cookie = should_use_secure_cookie(
        request_scheme=(request.url.scheme if request.url else None),
        x_forwarded_proto=request.headers.get("x-forwarded-proto"),
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=secure_cookie,
        max_age=session_ttl,
        path="/",
    )
    status["authenticated"] = True
    _auth_audit(
        request,
        "login_success",
        requiresAuth=bool(status.get("requiresAuth")),
        sessionTtlSeconds=session_ttl,
        secureCookie=bool(secure_cookie),
    )
    return {"ok": True, "auth": status}


@router.post("/api/auth/logout")
async def auth_logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    revoke_session(token)
    secure_cookie = should_use_secure_cookie(
        request_scheme=(request.url.scheme if request.url else None),
        x_forwarded_proto=request.headers.get("x-forwarded-proto"),
    )
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite="lax", secure=secure_cookie)
    _auth_audit(request, "logout", secureCookie=bool(secure_cookie), hadSessionCookie=bool(token))
    return {"ok": True}


@router.post("/api/auth/panel-access")
async def save_auth_panel_access(request: Request):
    body = await request.json()
    enabled = bool((body or {}).get("enabled", False))
    current_password = (body or {}).get("currentPassword")
    new_password = (body or {}).get("newPassword")
    try:
        status = save_panel_access(
            enabled=enabled,
            current_password=current_password,
            new_password=new_password,
        )
        _auth_audit(
            request,
            "panel_access_updated",
            enabled=bool(status.get("enabled")),
            configured=bool(status.get("configured")),
            requiresAuth=bool(status.get("requiresAuth")),
        )
        return {"ok": True, "auth": status}
    except ValueError as ex:
        _auth_audit(request, "panel_access_update_failed", level="warning", reason=str(ex))
        raise HTTPException(status_code=400, detail=str(ex))


@router.post("/api/system/migrate-secrets")
async def migrate_secrets(request: Request):
    result = migrate_all_secrets_in_config()
    _auth_audit(
        request,
        "secrets_migration_executed",
        changed=bool(result.get("changed")),
        settingsSecretsMigrated=int(result.get("settingsSecretsMigrated") or 0),
        storagesRecordsMigrated=int(result.get("storagesRecordsMigrated") or 0),
        repositoriesRecordsMigrated=int(result.get("repositoriesRecordsMigrated") or 0),
    )
    return result


@router.get("/api/system/paths")
async def get_system_paths():
    return {"ok": True, "paths": runtime_paths_info()}


@router.get("/api/system/update-check")
async def get_update_check():
    s = settings_config.read() or {}
    updates = dict(s.get("updates") or {})
    enabled = bool(updates.get("enabled", True))
    url = str(updates.get("url") or "").strip()
    base_payload = {
        "ok": True,
        "currentVersion": APP_VERSION,
        "enabled": enabled,
        "configured": bool(url),
        "sourceUrl": url,
        "checkOk": False,
        "updateAvailable": False,
        "latestVersion": None,
        "downloadUrl": None,
        "notesUrl": None,
        "publishedAt": None,
        "mandatory": False,
        "error": None,
    }
    if not enabled or not url:
        return base_payload

    try:
        remote = _fetch_json_url(url)
        latest_version = str(remote.get("version") or "").strip()
        download_url = str(remote.get("url") or "").strip()
        if not latest_version:
            raise ValueError("latest.json no contiene 'version'")
        base_payload.update({
            "checkOk": True,
            "latestVersion": latest_version,
            "downloadUrl": (download_url or None),
            "notesUrl": (str(remote.get("notesUrl") or "").strip() or None),
            "publishedAt": (str(remote.get("publishedAt") or "").strip() or None),
            "mandatory": bool(remote.get("mandatory", False)),
            "updateAvailable": _is_version_newer(latest_version, APP_VERSION),
        })
        return base_payload
    except urllib.error.HTTPError as ex:
        base_payload["error"] = f"HTTP {ex.code} al consultar updates"
        return base_payload
    except urllib.error.URLError as ex:
        base_payload["error"] = f"No se pudo consultar updates: {getattr(ex, 'reason', ex)}"
        return base_payload
    except Exception as ex:
        base_payload["error"] = f"Error validando latest.json: {ex}"
        return base_payload

# --- Config & Logs ---

@router.get("/api/config/settings")
async def get_settings():
    s = settings_config.read()
    if "duplicacyPath" not in s and "duplicacy_path" in s:
        s["duplicacyPath"] = s.get("duplicacy_path")
    # Descifrar secretos que la UI necesita mostrar/reutilizar
    try:
        n = dict(s.get("notifications") or {})
        mail = dict(n.get("email") or {})
        if "smtpPassword" in mail:
            mail["smtpPassword"] = reveal_secret(mail.get("smtpPassword")) or ""
        if mail:
            n["email"] = mail
            s["notifications"] = n
    except Exception:
        pass
    # No exponer el blob DPAPI del panel al frontend
    pa = dict(s.get("panelAccess") or {})
    if pa:
        pa.pop("passwordBlob", None)
        pa["configured"] = bool(get_panel_auth_public_status().get("configured"))
        s["panelAccess"] = pa
    return {"ok": True, "settings": s}

@router.put("/api/config/settings")
async def update_settings(req: Request):
    data = await req.json()
    if "duplicacyPath" in data and "duplicacy_path" not in data:
        data["duplicacy_path"] = data["duplicacyPath"]
    if "duplicacy_path" in data and "duplicacyPath" not in data:
        data["duplicacyPath"] = data["duplicacy_path"]
    current = settings_config.read()
    # La contraseña del panel se gestiona por endpoint dedicado
    if isinstance(data.get("panelAccess"), dict):
        incoming_panel_access = {
            k: v for k, v in data["panelAccess"].items()
            if k not in {"passwordBlob", "configured", "requiresAuth", "authenticated"}
        }
        merged_panel_access = dict(current.get("panelAccess") or {})
        merged_panel_access.update(incoming_panel_access)
        data["panelAccess"] = merged_panel_access
    if isinstance(data.get("notifications"), dict):
        n = dict(data.get("notifications") or {})
        mail = dict(n.get("email") or {})
        if "smtpPassword" in mail:
            mail["smtpPassword"] = protect_secret(mail.get("smtpPassword") or "") or ""
            n["email"] = mail
            data["notifications"] = n
    current.update(data)
    settings_config.write(current)
    return {"ok": True, "settings": current}

@router.get("/api/config/logs")
async def list_logs():
    return {"ok": True, "files": get_log_files()}

@router.get("/api/config/logs/{filename}/query")
async def query_log(
    filename: str,
    offset: int = 0,
    limit: int = 200,
    level: Optional[str] = None,
    op_type: Optional[str] = None,
    text: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    reverse: bool = True,
):
    content = read_log_file(filename)
    if content is None:
        raise HTTPException(status_code=404, detail="Log file not found")

    raw_lines = [ln for ln in str(content).splitlines() if ln.strip()]
    parsed = [_parse_log_line(ln) for ln in raw_lines]
    filtered = _apply_log_filters(
        parsed,
        level=level,
        op_type=op_type,
        text=text,
        date_from=date_from,
        date_to=date_to,
    )
    if reverse:
        filtered = list(reversed(filtered))
    offset = max(0, int(offset or 0))
    limit = max(1, min(1000, int(limit or 200)))
    page = filtered[offset: offset + limit]
    rows = [
        {
            "raw": r.get("raw") or "",
            "time": r.get("time") or "",
            "timeIso": r.get("timeIso"),
            "level": r.get("level") or "OTHER",
            "source": r.get("source") or "",
            "message": r.get("message") or "",
            "opType": r.get("opType"),
        }
        for r in page
    ]
    return {
        "ok": True,
        "filename": filename,
        "offset": offset,
        "limit": limit,
        "count": len(rows),
        "total": len(filtered),
        "hasMore": (offset + len(rows)) < len(filtered),
        "reverse": bool(reverse),
        "summary": _log_counts(filtered),
        "rows": rows,
    }

@router.get("/api/config/logs/{filename}/export")
async def export_log_filtered(
    filename: str,
    level: Optional[str] = None,
    op_type: Optional[str] = None,
    text: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    reverse: bool = True,
):
    content = read_log_file(filename)
    if content is None:
        raise HTTPException(status_code=404, detail="Log file not found")
    raw_lines = [ln for ln in str(content).splitlines() if ln.strip()]
    parsed = [_parse_log_line(ln) for ln in raw_lines]
    filtered = _apply_log_filters(
        parsed,
        level=level,
        op_type=op_type,
        text=text,
        date_from=date_from,
        date_to=date_to,
    )
    if reverse:
        filtered = list(reversed(filtered))
    body = "\n".join((r.get("raw") or "") for r in filtered)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename.replace(".log", "")}-filtrado.log"'
    }
    return PlainTextResponse(content=body, headers=headers)

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

