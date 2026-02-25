"""
DupliManager — Config Store (SQLite V2)
Gestión de configuración basada en SQLite para concurrencia segura.
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from server_py.utils.logger import get_logger

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
CONFIG_DIR.mkdir(exist_ok=True)

DB_PATH = CONFIG_DIR / "duplimanager.db"

# Valores por defecto
DEFAULTS = {
    "settings.json": {
        "host": "127.0.0.1",
        "port": 8500,
        "duplicacy_path": str(Path(__file__).parent.parent.parent / "bin" / "duplicacy.exe"),
        "language": "es",
        "theme": "dark",
        "cors": {
            "enabled": False,
            "allowOrigins": [],
            "allowMethods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allowHeaders": ["*"],
            "allowCredentials": False,
        },
        "notifications": {
            "healthchecks": {
                "enabled": False,
                "url": "",
                "successKeyword": "success",
                "timeoutSeconds": 10,
                "sendLog": True,
            },
            "email": {
                "enabled": False,
                "smtpHost": "",
                "smtpPort": 587,
                "smtpStartTls": True,
                "smtpUsername": "",
                "smtpPassword": "",
                "from": "",
                "to": "",
                "subjectPrefix": "[DupliManager]",
                "sendLog": True,
            }
        }
    },
    "repositories.json": [],
    "storages.json": [],
    "schedules.json": []
}

_db_lock = threading.Lock()
logger = get_logger("ConfigStore")

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
        """Escribe la config completa con validación de integridad."""
        if not isinstance(data, (list, dict)):
            logger.error(f"[ConfigStore] Intento de escribir datos no estructurados en {self.filename}: {type(data)}")
            return

        try:
            # Serializar y validar que el resultado es un JSON válido
            json_str = json.dumps(data, indent=2, ensure_ascii=False)
            # Doble comprobación de seguridad: intentar cargar lo que acabamos de serializar
            json.loads(json_str)
        except (TypeError, ValueError) as e:
            logger.error(f"[ConfigStore] Error de serialización en {self.filename}: {e}")
            return

        with _db_lock:
            with sqlite3.connect(DB_PATH, timeout=10.0) as conn:
                conn.execute(
                    "UPDATE config_store SET data = ? WHERE filename = ?",
                    (json_str, self.filename)
                )
                conn.commit()
                
        # Guardar también el JSON en modo sólo lectura (backup)
        try:
            (CONFIG_DIR / self.filename).write_text(json_str, encoding="utf-8")
        except Exception as e:
            logger.error(f"[ConfigStore] No se pudo escribir archivo de backup {self.filename}: {e}")


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


    def atomic_update(self, callback: Any) -> Any:
        """Realiza un ciclo de lectura-modificación-escritura atómico."""
        with _db_lock:
            with sqlite3.connect(DB_PATH, timeout=10.0) as conn:
                # 1. Leer
                cursor = conn.execute("SELECT data FROM config_store WHERE filename = ?", (self.filename,))
                row = cursor.fetchone()
                data = json.loads(row[0]) if row else DEFAULTS.get(self.filename, [])
                
                # 2. Modificar via callback
                new_data = callback(data)
                
                # 3. Validar y Escribir
                if not isinstance(new_data, (list, dict)):
                    logger.error(f"[ConfigStore] atomic_update rechazada: {type(new_data)} en {self.filename}")
                    return data

                json_str = json.dumps(new_data, indent=2, ensure_ascii=False)
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
                    
                return new_data


# ─── Singletons ──────────────────────────────────────
settings = ConfigStore("settings.json")
repositories = ConfigStore("repositories.json")
storages = ConfigStore("storages.json")
schedules = ConfigStore("schedules.json")

