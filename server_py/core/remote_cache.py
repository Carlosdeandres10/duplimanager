import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from server_py.utils.logger import get_logger

logger = get_logger("RemoteCache")

REMOTE_LIST_CACHE_TTL_SECONDS = 3600

CACHE_DIR = Path(__file__).parent.parent / "config" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
PROBES_DIR = CACHE_DIR / "probes"
PROBES_DIR.mkdir(parents=True, exist_ok=True)
LOOKUP_CACHE_FILE = CACHE_DIR / "lookup_cache.json"


def _load_remote_cache() -> Dict[str, Dict[str, Any]]:
    if LOOKUP_CACHE_FILE.exists():
        try:
            with open(LOOKUP_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


remote_storage_list_cache: Dict[str, Dict[str, Any]] = _load_remote_cache()


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


def _save_remote_cache() -> None:
    try:
        tmp_file = LOOKUP_CACHE_FILE.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(remote_storage_list_cache, f)
        tmp_file.replace(LOOKUP_CACHE_FILE)
    except Exception as e:
        logger.error(f"Error saving remote cache: {e}")


def _remote_cache_set(key: str, value: Any) -> None:
    remote_storage_list_cache[key] = {"ts": time.time(), "value": value}
    _save_remote_cache()

