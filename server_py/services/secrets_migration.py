"""
Migracion activa de secretos legacy a formato protegido (DPAPI) en configuracion.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from server_py.utils.config_store import settings as settings_config
from server_py.utils.config_store import storages as storages_config
from server_py.utils.config_store import repositories as repositories_config
from server_py.utils.logger import get_logger
from server_py.utils.secret_crypto import protect_secrets_deep, protect_secret, is_protected_secret

logger = get_logger("SecretsMigration")


def _migrate_settings(data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, int]]:
    changed = 0
    out = dict(data or {})
    n = dict(out.get("notifications") or {})
    mail = dict(n.get("email") or {})
    if "smtpPassword" in mail:
        before = str(mail.get("smtpPassword") or "")
        after = protect_secret(before) or ""
        if before != after:
            mail["smtpPassword"] = after
            changed += 1
    if mail:
        n["email"] = mail
        out["notifications"] = n
    return out, {"settingsSecretsMigrated": changed}


def _migrate_storages(data: Any) -> Tuple[Any, Dict[str, int]]:
    changed = 0
    storages = list(data or [])
    for item in storages:
        if not isinstance(item, dict):
            continue
        secrets = item.get("_secrets")
        if not isinstance(secrets, dict):
            continue
        before = dict(secrets)
        after = protect_secrets_deep(before)
        if before != after:
            item["_secrets"] = after
            changed += 1
    return storages, {"storagesRecordsMigrated": changed}


def _migrate_repositories(data: Any) -> Tuple[Any, Dict[str, int]]:
    changed = 0
    repos = list(data or [])
    for item in repos:
        if not isinstance(item, dict):
            continue
        secrets = item.get("_secrets")
        if not isinstance(secrets, dict):
            continue
        before = dict(secrets)
        after = protect_secrets_deep(before)
        if before != after:
            item["_secrets"] = after
            changed += 1
    return repos, {"repositoriesRecordsMigrated": changed}


def migrate_all_secrets_in_config() -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "ok": True,
        "settingsSecretsMigrated": 0,
        "storagesRecordsMigrated": 0,
        "repositoriesRecordsMigrated": 0,
    }

    settings_data = settings_config.read() or {}
    new_settings, s_stats = _migrate_settings(settings_data)
    summary.update(s_stats)
    if new_settings != settings_data:
        settings_config.write(new_settings)

    storages_data = storages_config.read() or []
    new_storages, st_stats = _migrate_storages(storages_data)
    summary.update(st_stats)
    if new_storages != storages_data:
        storages_config.write(new_storages)

    repos_data = repositories_config.read() or []
    new_repos, r_stats = _migrate_repositories(repos_data)
    summary.update(r_stats)
    if new_repos != repos_data:
        repositories_config.write(new_repos)

    summary["changed"] = any(
        int(summary.get(k) or 0) > 0
        for k in ("settingsSecretsMigrated", "storagesRecordsMigrated", "repositoriesRecordsMigrated")
    )
    logger.info(
        "[SecretsMigration] changed=%s settings=%s storages=%s repos=%s",
        summary.get("changed"),
        summary.get("settingsSecretsMigrated"),
        summary.get("storagesRecordsMigrated"),
        summary.get("repositoriesRecordsMigrated"),
    )
    return summary

