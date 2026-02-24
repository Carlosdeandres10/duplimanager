"""
DupliManager — Config Store (SQLite V2)
Gestión de configuración basada en SQLite para concurrencia segura.
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
CONFIG_DIR.mkdir(exist_ok=True)

DB_PATH = CONFIG_DIR / "duplimanager.db"

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

_db_lock = threading.Lock()

def _init_db():
    with _db_lock:
        with sqlite3.connect(DB_PATH, timeout=10.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS config_store (
                    filename TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                )
                """
            )
            conn.commit()

            # Migración desde JSON a SQLite si existen
            for filename in DEFAULTS.keys():
                cursor = conn.execute("SELECT 1 FROM config_store WHERE filename = ?", (filename,))
                if not cursor.fetchone():
                    # Intenta leer el JSON antiguo
                    old_file = CONFIG_DIR / filename
                    data_to_insert = DEFAULTS[filename]
                    if old_file.exists():
                        try:
                            data_to_insert = json.loads(old_file.read_text(encoding="utf-8"))
                        except Exception:
                            pass
                    conn.execute("INSERT INTO config_store (filename, data) VALUES (?, ?)", 
                                 (filename, json.dumps(data_to_insert, ensure_ascii=False)))
            conn.commit()


_init_db()

class ConfigStore:
    """Almacén de config SQLite con lectura/escritura thread-safe."""

    def __init__(self, filename: str):
        self.filename = filename

    def read(self) -> Any:
        """Lee y retorna la config."""
        with _db_lock:
            with sqlite3.connect(DB_PATH, timeout=10.0) as conn:
                cursor = conn.execute("SELECT data FROM config_store WHERE filename = ?", (self.filename,))
                row = cursor.fetchone()
                if row:
                    try:
                        return json.loads(row[0])
                    except json.JSONDecodeError:
                        return DEFAULTS.get(self.filename, {})
                return DEFAULTS.get(self.filename, {})

    def write(self, data: Any):
        """Escribe la config completa."""
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        with _db_lock:
            with sqlite3.connect(DB_PATH, timeout=10.0) as conn:
                conn.execute(
                    "UPDATE config_store SET data = ? WHERE filename = ?",
                    (json_str, self.filename)
                )
                conn.commit()
                
        # Guardar también el JSON en modo sólo lectura (backup) para no romper scripts externos
        try:
            (CONFIG_DIR / self.filename).write_text(json_str, encoding="utf-8")
        except Exception:
            pass

    def update(self, key: str, value: Any) -> Any:
        """Actualiza un valor usando dot notation."""
        # Se lee de la BBDD, se modifica en RAM y se vuelve a escribir atómicamente en un lock.
        with _db_lock:
            with sqlite3.connect(DB_PATH, timeout=10.0) as conn:
                cursor = conn.execute("SELECT data FROM config_store WHERE filename = ?", (self.filename,))
                row = cursor.fetchone()
                data = json.loads(row[0]) if row else DEFAULTS.get(self.filename, {})
                
                keys = key.split(".")
                obj = data
                for k in keys[:-1]:
                    if k not in obj:
                        obj[k] = {}
                    obj = obj[k]
                obj[keys[-1]] = value
                
                json_str = json.dumps(data, indent=2, ensure_ascii=False)
                conn.execute(
                    "UPDATE config_store SET data = ? WHERE filename = ?",
                    (json_str, self.filename)
                )
                conn.commit()
                
        # Respaldo JSON asíncrono secundario
        try:
            (CONFIG_DIR / self.filename).write_text(json_str, encoding="utf-8")
        except Exception:
            pass
            
        return data


# ─── Singletons ──────────────────────────────────────
settings = ConfigStore("settings.json")
repositories = ConfigStore("repositories.json")
storages = ConfigStore("storages.json")
schedules = ConfigStore("schedules.json")
