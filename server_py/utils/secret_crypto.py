"""
Utilidades de proteccion de secretos en reposo (Windows DPAPI).

Compatibilidad:
- Si el valor ya esta cifrado -> se mantiene.
- Si el valor esta en claro -> puede leerse y se cifra al reescribir.
- En sistemas no Windows, se deja el valor en claro (compatibilidad de desarrollo).
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wintypes
from typing import Any, Dict, Optional

from server_py.utils.logger import get_logger

logger = get_logger("SecretCrypto")

SECRET_PREFIX = "dpapi$"
CRYPTPROTECT_UI_FORBIDDEN = 0x1
CRYPTPROTECT_LOCAL_MACHINE = 0x4


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _is_windows() -> bool:
    try:
        return bool(ctypes.windll)  # type: ignore[attr-defined]
    except Exception:
        return False


def _blob_from_bytes(data: bytes):
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


def is_protected_secret(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(SECRET_PREFIX)


def protect_secret(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if not text:
        return text
    if is_protected_secret(text):
        return text
    if not _is_windows():
        return text
    try:
        protected = _dpapi_protect(text.encode("utf-8"))
        return SECRET_PREFIX + base64.b64encode(protected).decode("ascii")
    except Exception as ex:
        logger.warning("[SecretCrypto] No se pudo proteger secreto con DPAPI; se mantiene en claro: %s", ex)
        return text


def reveal_secret(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if not text:
        return text
    if not is_protected_secret(text):
        return text
    if not _is_windows():
        return text
    raw_b64 = text[len(SECRET_PREFIX):]
    try:
        raw = _dpapi_unprotect(base64.b64decode(raw_b64.encode("ascii")))
        return raw.decode("utf-8")
    except Exception as ex:
        logger.warning("[SecretCrypto] No se pudo descifrar secreto DPAPI: %s", ex)
        return None


def _is_secret_field_name(field_name: str) -> bool:
    key = str(field_name or "")
    return key in {
        "accessId",
        "accessKey",
        "duplicacyPassword",
        "smtpPassword",
        "password",
    } or key.endswith("_PASSWORD")


def protect_secrets_deep(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if _is_secret_field_name(str(k)) and v not in (None, ""):
                out[k] = protect_secret(str(v))
            else:
                out[k] = protect_secrets_deep(v)
        return out
    if isinstance(obj, list):
        return [protect_secrets_deep(x) for x in obj]
    return obj

