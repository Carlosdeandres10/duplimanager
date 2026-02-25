import os
import re
from typing import Dict, Any, Optional, List
from fastapi import HTTPException
from server_py.utils.logger import get_logger
from server_py.utils import config_store
from server_py.utils.secret_crypto import reveal_secret
from server_py.models.schemas import RepoCreate, RepoUpdate

logger = get_logger("StorageHelpers")
INTERNAL_STORAGE_SECRET_KEYS = {"_secrets", "accessId", "accessKey", "duplicacyPassword"}


def normalize_storage_comparable_url(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").rstrip("/").lower()


def repo_matches_storage_record(repo: Dict[str, Any], storage: Dict[str, Any]) -> bool:
    if not repo or not storage:
        return False

    primary = get_primary_storage(repo) or {}
    repo_type = str(primary.get("type") or ("wasabi" if "wasabi://" in str(repo.get("storageUrl") or "").lower() else "local")).lower()
    storage_type = str(storage.get("type") or "").lower()
    repo_url = normalize_storage_comparable_url(primary.get("url") or repo.get("storageUrl") or "")
    storage_url = normalize_storage_comparable_url(storage.get("url") or storage.get("localPath") or "")

    # Regla sólida: si hay URL/ruta real, se compara por tipo + URL.
    if repo_url and storage_url:
        if repo_type and storage_type and repo_type != storage_type:
            return False
        return repo_url == storage_url

    # Fallback legacy: solo si falta URL en el repo.
    return bool(repo.get("storageRefId") and storage.get("id") and repo.get("storageRefId") == storage.get("id"))

def sanitize_storage(storage: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(storage)
    for key in INTERNAL_STORAGE_SECRET_KEYS:
        sanitized.pop(key, None)
    # Expose safe flags for UI
    secrets = storage.get("_secrets") or {}
    sanitized["hasWasabiCredentials"] = bool(reveal_secret(secrets.get("accessId")) and reveal_secret(secrets.get("accessKey")))
    sanitized["hasDuplicacyPassword"] = bool(reveal_secret(secrets.get("duplicacyPassword")))
    return sanitized

def get_storage_by_id(storage_id: str) -> Optional[Dict[str, Any]]:
    # Buscamos en todos los storages (gestionados + derivados) para evitar errores 404 en backups legacy
    storages = list_all_storages_for_ui()
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

def describe_storage(repo: Dict[str, Any], storage_name: Optional[str] = None) -> str:
    primary = get_repo_storage(repo, storage_name) or get_primary_storage(repo) or {}
    label = primary.get("label") or primary.get("name") or "default"
    url = primary.get("url") or repo.get("storageUrl") or "—"
    return f"{label} -> {url}"

def get_storage_env(repo: Dict[str, Any], storage_name: Optional[str] = None) -> Dict[str, str]:
    target_name = storage_name or (get_primary_storage(repo) or {}).get("name")
    if not target_name:
        return {}

    storage = get_repo_storage(repo, target_name)
    if not storage:
        return {}

    if storage.get("type") != "wasabi":
        return {}

    # Prioritizar secretos locales del repo
    secrets = (repo.get("_secrets") or {}).get(target_name, {})
    access_id = reveal_secret(secrets.get("accessId"))
    access_key = reveal_secret(secrets.get("accessKey"))

    # Fallback a secretos centralizados si hay storageRefId
    if (not access_id or not access_key) and repo.get("storageRefId"):
        central_storage = get_storage_by_id(repo["storageRefId"])
        if central_storage:
            central_secrets = central_storage.get("_secrets") or {}
            access_id = access_id or reveal_secret(central_secrets.get("accessId"))
            access_key = access_key or reveal_secret(central_secrets.get("accessKey"))

    if not access_id or not access_key:
        return {}

    return build_wasabi_env(access_id, access_key, target_name)

def get_repo_duplicacy_password(repo: Dict[str, Any], storage_name: Optional[str] = None) -> Optional[str]:
    """Recupera la contraseña de cifrado buscando en repo o en el storage vinculado"""
    target_name = storage_name or (get_primary_storage(repo) or {}).get("name", "default")
    
    # 1. Buscar en secrets del repo (estructura anidada por alias)
    repo_secrets = repo.get("_secrets") or {}
    pwd_nest = reveal_secret(repo_secrets.get(target_name, {}).get(f"{target_name}_PASSWORD"))
    if pwd_nest: return pwd_nest

    # 2. Buscar en secrets del repo (estructura plana legacy)
    pwd_flat = reveal_secret(repo_secrets.get(f"{target_name}_PASSWORD")) or reveal_secret(repo_secrets.get("password"))
    if pwd_flat: return pwd_flat

    # 3. Buscar en el storage vinculado centralmente
    ref_id = repo.get("storageRefId")
    if ref_id:
        storage = get_storage_by_id(ref_id)
        if storage:
            storage_secrets = storage.get("_secrets") or {}
            return reveal_secret(storage_secrets.get("duplicacyPassword"))
    
    return None

def build_wasabi_env(access_id: str, access_key: str, storage_name: str = "default") -> Dict[str, str]:
    access_id = (access_id or "").strip()
    access_key = (access_key or "").strip()
    if not access_id or not access_key:
        return {}
    import re
    alias = (storage_name or "default").strip()
    safe_alias = re.sub(r"[^A-Za-z0-9]", "_", alias).upper()

    return {
        "WASABI_KEY": access_id,
        "WASABI_SECRET": access_key,
        "DUPLICACY_WASABI_KEY": access_id,
        "DUPLICACY_WASABI_SECRET": access_key,
        "DUPLICACY_S3_ID": access_id,
        "DUPLICACY_S3_SECRET": access_key,
        f"DUPLICACY_{safe_alias}_S3_ID": access_id,
        f"DUPLICACY_{safe_alias}_S3_SECRET": access_key,
        f"DUPLICACY_{safe_alias}_WASABI_KEY": access_id,
        f"DUPLICACY_{safe_alias}_WASABI_SECRET": access_key,
    }

def get_storage_record_env(storage: Dict[str, Any], storage_name: str = "default") -> Dict[str, str]:
    if (storage.get("type") or "").lower() != "wasabi":
        return {}
    secrets = storage.get("_secrets") or {}
    return build_wasabi_env(reveal_secret(secrets.get("accessId")) or "", reveal_secret(secrets.get("accessKey")) or "", storage_name)

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
        access_id = reveal_secret(sec.get("accessId"))
        access_key = reveal_secret(sec.get("accessKey"))
        if access_id and access_key:
            secrets = {"default": {"accessId": access_id, "accessKey": access_key}}

    return {
        "destinationType": storage_type,
        "storageUrl": base_storage["url"],
        "storage": base_storage,
        "extraEnv": get_storage_record_env(storage, storage.get("region") or "default"),
        "secrets": secrets,

        "storageRefId": storage.get("id"),
        "storageDuplicacyPassword": (reveal_secret((storage.get("_secrets") or {}).get("duplicacyPassword")) or None),
    }

def list_all_storages_for_ui() -> List[Dict[str, Any]]:
    explicit = config_store.storages.read()
    repos_data = config_store.repositories.read()

    by_id: Dict[str, Dict[str, Any]] = {}
    
    # Solo procesamos storages configurados explícitamente
    for s in explicit:
        item = dict(s)
        item.setdefault("source", "managed")
        item.setdefault("linkedBackups", 0)
        item.setdefault("fromRepoIds", [])
        storage_id = item.get("id")
        if storage_id:
            by_id[storage_id] = item

    # Enlazar backups por destino real (tipo + URL/ruta); storageRefId queda como fallback legacy
    for repo in repos_data:
        repo_id = repo.get("id")
        if not repo_id:
            continue
        for matched in by_id.values():
            if repo_matches_storage_record(repo, matched):
                if repo_id not in matched["fromRepoIds"]:
                    matched["fromRepoIds"].append(repo_id)
                    matched["linkedBackups"] += 1

    result = list(by_id.values())
    # Ordenar por nombre
    result.sort(key=lambda s: str(s.get("name") or "").lower())
    return result

