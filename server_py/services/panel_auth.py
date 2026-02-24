"""
Autenticación local del panel web (Windows DPAPI + sesión por cookie).

Objetivo MVP:
- Proteger el acceso al panel/API con una contraseña local.
- Guardar el verificador de contraseña cifrado con Windows (DPAPI).
- Mantener sesiones simples en memoria (cookie HttpOnly).
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wintypes
import hashlib
import hmac
import json
import secrets
import time
from typing import Dict, Any, Optional

from server_py.utils.config_store import settings as settings_config
from server_py.utils.logger import get_logger

logger = get_logger("PanelAuth")

SESSION_COOKIE_NAME = "duplimanager_session"
SESSION_TTL_SECONDS = 12 * 60 * 60
_sessions: Dict[str, float] = {}


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


CRYPTPROTECT_UI_FORBIDDEN = 0x1
CRYPTPROTECT_LOCAL_MACHINE = 0x4


def _is_windows() -> bool:
    try:
        return bool(ctypes.windll)  # type: ignore[attr-defined]
    except Exception:
        return False


def _blob_from_bytes(data: bytes) -> tuple[_DATA_BLOB, Any]:
    if not data:
        arr = (ctypes.c_byte * 1)()
        return _DATA_BLOB(0, arr), arr
    arr = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    return _DATA_BLOB(len(data), arr), arr


def _bytes_from_blob(blob: _DATA_BLOB) -> bytes:
    if not blob.cbData or not blob.pbData:
        return b""
    return ctypes.string_at(blob.pbData, blob.cbData)


def _dpapi_protect(data: bytes) -> bytes:
    if not _is_windows():
        raise RuntimeError("DPAPI solo disponible en Windows")
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    in_blob, _arr = _blob_from_bytes(data)
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN | CRYPTPROTECT_LOCAL_MACHINE,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return _bytes_from_blob(out_blob)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    if not _is_windows():
        raise RuntimeError("DPAPI solo disponible en Windows")
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    in_blob, _arr = _blob_from_bytes(data)
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return _bytes_from_blob(out_blob)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)


def _pbkdf2_hash(password: str, salt: bytes) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return base64.b64encode(dk).decode("ascii")


def _read_panel_access_cfg() -> Dict[str, Any]:
    s = settings_config.read() or {}
    pa = dict(s.get("panelAccess") or {})
    return {
        "enabled": bool(pa.get("enabled", False)),
        "passwordBlob": str(pa.get("passwordBlob") or "").strip(),
        "sessionTtlSeconds": int(pa.get("sessionTtlSeconds") or SESSION_TTL_SECONDS),
    }


def _write_panel_access_cfg(enabled: bool, password_blob: Optional[str]) -> Dict[str, Any]:
    current = settings_config.read() or {}
    pa = dict(current.get("panelAccess") or {})
    pa["enabled"] = bool(enabled)
    pa["sessionTtlSeconds"] = int(pa.get("sessionTtlSeconds") or SESSION_TTL_SECONDS)
    if password_blob is not None:
        pa["passwordBlob"] = str(password_blob or "").strip()
    current["panelAccess"] = pa
    settings_config.write(current)
    return pa


def _encode_password_verifier(password: str) -> str:
    salt = secrets.token_bytes(16)
    payload = {
        "v": 1,
        "salt": base64.b64encode(salt).decode("ascii"),
        "hash": _pbkdf2_hash(password, salt),
        "algo": "pbkdf2-sha256",
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    protected = _dpapi_protect(raw)
    return base64.b64encode(protected).decode("ascii")


def _decode_password_verifier(blob_b64: str) -> Dict[str, Any]:
    raw = _dpapi_unprotect(base64.b64decode(blob_b64.encode("ascii")))
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Formato de verificador inválido")
    return data


def has_panel_password() -> bool:
    cfg = _read_panel_access_cfg()
    return bool(cfg.get("passwordBlob"))


def is_panel_auth_enabled() -> bool:
    cfg = _read_panel_access_cfg()
    return bool(cfg.get("enabled")) and bool(cfg.get("passwordBlob"))


def get_public_status() -> Dict[str, Any]:
    cfg = _read_panel_access_cfg()
    return {
        "enabled": bool(cfg.get("enabled")),
        "configured": bool(cfg.get("passwordBlob")),
        "requiresAuth": bool(cfg.get("enabled")) and bool(cfg.get("passwordBlob")),
    }


def verify_panel_password(password: str) -> bool:
    cfg = _read_panel_access_cfg()
    blob_b64 = str(cfg.get("passwordBlob") or "").strip()
    if not blob_b64:
        return False
    try:
        payload = _decode_password_verifier(blob_b64)
        salt = base64.b64decode(str(payload.get("salt") or "").encode("ascii"))
        expected = str(payload.get("hash") or "")
        actual = _pbkdf2_hash(password or "", salt)
        return hmac.compare_digest(expected, actual)
    except Exception as ex:
        logger.warning("[Auth] No se pudo verificar password del panel: %s", ex)
        return False


def save_panel_access(*, enabled: bool, new_password: Optional[str], current_password: Optional[str]) -> Dict[str, Any]:
    existing_cfg = _read_panel_access_cfg()
    has_existing = bool(existing_cfg.get("passwordBlob"))
    current_password = (current_password or "").strip()
    new_password = (new_password or "").strip()

    if has_existing and not verify_panel_password(current_password):
        raise ValueError("La contraseña actual no es correcta.")

    password_blob: Optional[str] = None
    if has_existing:
        password_blob = existing_cfg.get("passwordBlob") or ""

    if enabled:
        if new_password:
            if len(new_password) < 4:
                raise ValueError("La nueva contraseña debe tener al menos 4 caracteres.")
            password_blob = _encode_password_verifier(new_password)
        elif not has_existing:
            raise ValueError("Debes indicar una nueva contraseña para activar la protección del panel.")
    else:
        # Desactivar: conservamos el verificador para permitir reactivar sin reescribir si no se cambia password.
        if new_password:
            if len(new_password) < 4:
                raise ValueError("La nueva contraseña debe tener al menos 4 caracteres.")
            password_blob = _encode_password_verifier(new_password)

    saved = _write_panel_access_cfg(bool(enabled), password_blob)
    return {
        "enabled": bool(saved.get("enabled")),
        "configured": bool(saved.get("passwordBlob")),
        "requiresAuth": bool(saved.get("enabled")) and bool(saved.get("passwordBlob")),
    }


def _cleanup_sessions() -> None:
    now = time.time()
    expired = [k for k, exp in _sessions.items() if exp <= now]
    for k in expired:
        _sessions.pop(k, None)


def create_session() -> str:
    _cleanup_sessions()
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_TTL_SECONDS
    return token


def revoke_session(token: Optional[str]) -> None:
    if token:
        _sessions.pop(token, None)


def is_session_valid(token: Optional[str]) -> bool:
    _cleanup_sessions()
    if not token:
        return False
    exp = _sessions.get(token)
    if not exp:
        return False
    if exp <= time.time():
        _sessions.pop(token, None)
        return False
    # Sliding session
    _sessions[token] = time.time() + SESSION_TTL_SECONDS
    return True

