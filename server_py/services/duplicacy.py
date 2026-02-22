"""
DupliManager — Duplicacy CLI Service
Wrapper around the duplicacy CLI binary using subprocess.
"""

import os
import subprocess
import re
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List
from server_py.utils.logger import get_logger
from server_py.utils import config_store

logger = get_logger("DuplicacyCLI")

class DuplicacyService:
    def __init__(self):
        settings_data = config_store.settings.read()
        self.binary_path = settings_data.get("duplicacy_path")

    def refresh_binary_path(self):
        settings_data = config_store.settings.read()
        self.binary_path = settings_data.get("duplicacy_path")

    async def exec(
        self, 
        args: List[str], 
        cwd: str, 
        env: Optional[Dict[str, str]] = None,
        on_progress: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """Ejecuta un comando duplicacy y captura la salida."""
        self.refresh_binary_path()
        logger.info(f"Ejecutando: duplicacy {' '.join(args)} en {cwd}")

        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        try:
            # Usar shell=False para mayor seguridad
            process = subprocess.Popen(
                [self.binary_path] + args,
                cwd=cwd,
                env=full_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # Combinar stderr en stdout
                text=True,
                encoding="utf-8",
                bufsize=1,
                universal_newlines=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            stdout_content = []
            
            # Leer salida línea a línea en tiempo real
            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    stdout_content.append(line)
                    if on_progress:
                        on_progress(line)
                process.stdout.close()

            return_code = process.wait()
            logger.info(f"Proceso finalizado con código {return_code}")

            full_output = "".join(stdout_content)
            return {
                "code": return_code,
                "stdout": full_output,
                "stderr": "" # Stderr ya está en stdout
            }

        except Exception as e:
            logger.error(f"Error ejecutando proceso: {str(e)}")
            return {
                "code": -1,
                "stdout": "",
                "stderr": str(e)
            }

    # ─── COMANDOS ───────────────────────────────────────────────

    async def init(self, repo_path: str, snapshot_id: str, storage_url: str, password: Optional[str] = None, encrypt: bool = True):
        args = ["init"]
        if not encrypt:
            args.append("-encrypt=false")
        args.extend([snapshot_id, storage_url])

        env = {}
        if password:
            env["DUPLICACY_PASSWORD"] = password

        return await self.exec(args, repo_path, env=env)

    async def backup(self, repo_path: str, password: Optional[str] = None, threads: Optional[int] = None, on_progress: Optional[Callable[[str], None]] = None):
        args = ["backup", "-stats"]
        if threads:
            args.extend(["-threads", str(threads)])

        env = {}
        if password:
            env["DUPLICACY_PASSWORD"] = password

        return await self.exec(args, repo_path, env=env, on_progress=on_progress)

    async def list_snapshots(self, repo_path: str, password: Optional[str] = None):
        args = ["list"]
        env = {}
        if password:
            env["DUPLICACY_PASSWORD"] = password

        result = await self.exec(args, repo_path, env=env)
        result["snapshots"] = self._parse_list_output(result["stdout"])
        return result

    async def restore(self, repo_path: str, revision: int, overwrite: bool = True, password: Optional[str] = None, on_progress: Optional[Callable[[str], None]] = None):
        args = ["restore", "-r", str(revision)]
        if overwrite:
            args.append("-overwrite")

        env = {}
        if password:
            env["DUPLICACY_PASSWORD"] = password

        return await self.exec(args, repo_path, env=env, on_progress=on_progress)

    # ─── PARSERS ────────────────────────────────────────────────

    def _parse_list_output(self, stdout: str) -> List[Dict[str, Any]]:
        snapshots = []
        # Patrón: Snapshot <id> revision <rev> created at <datetime> ...
        regex = re.compile(r"Snapshot\s+(\S+)\s+revision\s+(\d+)\s+created\s+at\s+(.+)", re.IGNORECASE)

        for line in stdout.splitlines():
            match = regex.search(line)
            if match:
                snapshots.append({
                    "id": match.group(1),
                    "revision": int(match.group(2)),
                    "createdAt": match.group(3).strip()
                })
        return snapshots

# Singleton
service = DuplicacyService()
