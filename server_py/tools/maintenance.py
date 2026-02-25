"""
CLI local de mantenimiento (sin backdoor web) para soporte/administracion.

Uso:
  python -m server_py.tools.maintenance panel-auth-status
  python -m server_py.tools.maintenance panel-auth-unlock --clear-password
  python -m server_py.tools.maintenance panel-auth-set --enable
  python -m server_py.tools.maintenance migrate-secrets
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from typing import Any

from server_py.services.panel_auth import (
    maintenance_get_panel_access_status,
    maintenance_disable_panel_auth,
    maintenance_set_panel_password,
)
from server_py.services.secrets_migration import migrate_all_secrets_in_config
from server_py.utils.logger import get_logger

logger = get_logger("MaintenanceCLI")


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_panel_auth_status(_args: argparse.Namespace) -> int:
    data = maintenance_get_panel_access_status()
    _print_json({"ok": True, "panelAuth": data})
    return 0


def cmd_panel_auth_unlock(args: argparse.Namespace) -> int:
    result = maintenance_disable_panel_auth(clear_password=bool(args.clear_password))
    logger.warning("[MaintenanceCLI] panel-auth-unlock clear_password=%s", bool(args.clear_password))
    _print_json({"ok": True, "action": "panel-auth-unlock", "result": result})
    return 0


def cmd_panel_auth_set(args: argparse.Namespace) -> int:
    password = args.password
    if not password:
        p1 = getpass.getpass("Nueva contraseña del panel: ")
        p2 = getpass.getpass("Confirmar contraseña: ")
        if p1 != p2:
            print("Error: la confirmación no coincide.", file=sys.stderr)
            return 2
        password = p1
    try:
        result = maintenance_set_panel_password(password=password, enable=bool(args.enable))
    except ValueError as ex:
        print(f"Error: {ex}", file=sys.stderr)
        return 2
    logger.warning("[MaintenanceCLI] panel-auth-set enable=%s", bool(args.enable))
    _print_json({"ok": True, "action": "panel-auth-set", "result": result})
    return 0


def cmd_migrate_secrets(_args: argparse.Namespace) -> int:
    result = migrate_all_secrets_in_config()
    logger.warning("[MaintenanceCLI] migrate-secrets changed=%s", bool(result.get("changed")))
    _print_json(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m server_py.tools.maintenance",
        description="Herramienta local de mantenimiento de DupliManager (servidor Windows).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("panel-auth-status", help="Mostrar estado de protección del panel")
    p_status.set_defaults(func=cmd_panel_auth_status)

    p_unlock = sub.add_parser(
        "panel-auth-unlock",
        help="Desactivar protección del panel localmente (mantenimiento).",
    )
    p_unlock.add_argument(
        "--clear-password",
        action="store_true",
        help="Borra el passwordBlob además de desactivar la protección.",
    )
    p_unlock.set_defaults(func=cmd_panel_auth_unlock)

    p_set = sub.add_parser(
        "panel-auth-set",
        help="Definir una contraseña del panel localmente (sin conocer la actual).",
    )
    p_set.add_argument(
        "--password",
        help="Contraseña nueva (evitar si no es necesario; mejor usar prompt).",
    )
    p_set.add_argument(
        "--enable",
        action="store_true",
        help="Activa la protección del panel tras establecer la contraseña (recomendado).",
    )
    p_set.set_defaults(func=cmd_panel_auth_set)

    p_migrate = sub.add_parser(
        "migrate-secrets",
        help="Migrar secretos legacy en configuración al formato protegido con DPAPI.",
    )
    p_migrate.set_defaults(func=cmd_migrate_secrets)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

