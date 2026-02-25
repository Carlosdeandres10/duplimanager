"""
DupliManager — Runtime paths
Centraliza rutas para modo desarrollo y modo empaquetado (PyInstaller/frozen).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict


def _project_root_from_source() -> Path:
    # server_py/utils/paths.py -> utils -> server_py -> repo root
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _project_root_from_source()
IS_FROZEN = bool(getattr(sys, "frozen", False))

if IS_FROZEN:
    INSTALL_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", INSTALL_DIR / "_internal")).resolve()
    DATA_DIR = INSTALL_DIR
else:
    INSTALL_DIR = PROJECT_ROOT
    BUNDLE_DIR = PROJECT_ROOT
    DATA_DIR = PROJECT_ROOT

CONFIG_DIR = DATA_DIR / "config"
LOGS_DIR = DATA_DIR / "logs"
BIN_DIR = BUNDLE_DIR / "bin"
WEB_DIR = BUNDLE_DIR / "web"
DOCS_HTML_PATH = DATA_DIR / "docs.html"
DOCS_DIR = DATA_DIR / "docs"
CACHE_DIR = CONFIG_DIR / "cache"
REMOTE_CACHE_DIR = CACHE_DIR
REMOTE_CACHE_PROBES_DIR = REMOTE_CACHE_DIR / "probes"
DEFAULT_DUPLICACY_EXE = BIN_DIR / "duplicacy.exe"


def ensure_runtime_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    REMOTE_CACHE_PROBES_DIR.mkdir(parents=True, exist_ok=True)


def runtime_paths_info() -> Dict[str, Any]:
    return {
        "frozen": IS_FROZEN,
        "projectRoot": str(PROJECT_ROOT),
        "installDir": str(INSTALL_DIR),
        "bundleDir": str(BUNDLE_DIR),
        "dataDir": str(DATA_DIR),
        "configDir": str(CONFIG_DIR),
        "logsDir": str(LOGS_DIR),
        "cacheDir": str(CACHE_DIR),
        "webDir": str(WEB_DIR),
        "docsDir": str(DOCS_DIR),
        "docsHtmlPath": str(DOCS_HTML_PATH),
        "defaultDuplicacyPath": str(DEFAULT_DUPLICACY_EXE),
        "pythonExecutable": str(Path(sys.executable).resolve()),
    }
