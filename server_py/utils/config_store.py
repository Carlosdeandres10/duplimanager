"""
DupliManager — Config Store
Gestión de configuración basada en archivos JSON.
"""

import json
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
CONFIG_DIR.mkdir(exist_ok=True)

# Valores por defecto
DEFAULTS = {
    "settings.json": {
        "port": 8500,
        "duplicacy_path": str(Path(__file__).parent.parent.parent / "bin" / "duplicacy.exe"),
        "language": "es",
        "theme": "dark",
        "notifications": {
            "enabled": False,
            "email": None,
            "webhook": None
        }
    },
    "repositories.json": [],
    "storages.json": [],
    "schedules.json": []
}


class ConfigStore:
    """Almacén de config JSON con lectura/escritura thread-safe."""

    def __init__(self, filename: str):
        self.filepath = CONFIG_DIR / filename
        self.filename = filename
        self._ensure_file()

    def _ensure_file(self):
        if not self.filepath.exists():
            default = DEFAULTS.get(self.filename, {})
            self.filepath.write_text(
                json.dumps(default, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )

    def read(self) -> Any:
        """Lee y retorna la config."""
        try:
            return json.loads(self.filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return DEFAULTS.get(self.filename, {})

    def write(self, data: Any):
        """Escribe la config completa."""
        self.filepath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def update(self, key: str, value: Any) -> Any:
        """Actualiza un valor usando dot notation. Ej: update('notifications.enabled', True)"""
        data = self.read()
        keys = key.split(".")
        obj = data
        for k in keys[:-1]:
            if k not in obj:
                obj[k] = {}
            obj = obj[k]
        obj[keys[-1]] = value
        self.write(data)
        return data


# ─── Singletons ──────────────────────────────────────
settings = ConfigStore("settings.json")
repositories = ConfigStore("repositories.json")
storages = ConfigStore("storages.json")
schedules = ConfigStore("schedules.json")
