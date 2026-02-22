"""
DupliManager — Logger Utility
Archivo de logging con rotación diaria y salida a consola.
"""

import os
import logging
from datetime import datetime
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)


def get_logger(name: str = "DupliManager") -> logging.Logger:
    """Crea un logger con salida a consola y archivo diario."""
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # Ya configurado

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Consola
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # Archivo diario
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = LOGS_DIR / f"duplimanager-{date_str}.log"
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


def get_log_files() -> list[str]:
    """Lista los archivos de log disponibles."""
    if not LOGS_DIR.exists():
        return []
    return sorted(
        [f.name for f in LOGS_DIR.glob("*.log")],
        reverse=True
    )


def read_log_file(filename: str) -> str | None:
    """Lee el contenido de un archivo de log."""
    filepath = LOGS_DIR / filename
    if not filepath.exists():
        return None
    return filepath.read_text(encoding="utf-8")
