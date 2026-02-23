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
        self.binary_path = settings_data.get("duplicacy_path") or settings_data.get("duplicacyPath")

    def refresh_binary_path(self):
        settings_data = config_store.settings.read()
        self.binary_path = settings_data.get("duplicacy_path") or settings_data.get("duplicacyPath")

    async def exec(
        self, 
        args: List[str], 
        cwd: str, 
        env: Optional[Dict[str, str]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        on_process_start: Optional[Callable[[Any], None]] = None,
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
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # Combinar stderr en stdout
                text=True,
                encoding="utf-8",
                bufsize=1,
                universal_newlines=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            if on_process_start:
                on_process_start(process)

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

    def _build_password_env(self, password: Optional[str], storage_name: Optional[str] = None) -> Dict[str, str]:
        env: Dict[str, str] = {}
        if not password:
            return env
        env["DUPLICACY_PASSWORD"] = password
        # Duplicacy may request the storage password using the storage alias env var.
        alias = (storage_name or "default").strip()
        if alias:
            safe_alias = re.sub(r"[^A-Za-z0-9]", "_", alias).upper()
            env[f"DUPLICACY_{safe_alias}_PASSWORD"] = password
        return env

    async def init(self, repo_path: str, snapshot_id: str, storage_url: str, password: Optional[str] = None, encrypt: bool = True, extra_env: Optional[Dict[str, str]] = None):
        args = ["init"]
        if encrypt:
            args.append("-e")
        else:
            args.append("-encrypt=false")
        args.extend([snapshot_id, storage_url])

        env = self._build_password_env(password, "default")
        if extra_env:
            env.update(extra_env)

        return await self.exec(args, repo_path, env=env)

    async def add_storage(
        self,
        repo_path: str,
        storage_name: str,
        snapshot_id: str,
        storage_url: str,
        password: Optional[str] = None,
        encrypt: bool = True,
        extra_env: Optional[Dict[str, str]] = None,
    ):
        args = ["add"]
        if encrypt:
            args.append("-e")
        args.extend([storage_name, snapshot_id, storage_url])

        env = self._build_password_env(password, storage_name)
        if extra_env:
            env.update(extra_env)

        return await self.exec(args, repo_path, env=env)

    async def backup(
        self,
        repo_path: str,
        password: Optional[str] = None,
        threads: Optional[int] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        storage_name: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None,
        on_process_start: Optional[Callable[[Any], None]] = None,
    ):
        args = ["backup", "-stats"]
        if storage_name:
            args.extend(["-storage", storage_name])
        if threads:
            args.extend(["-threads", str(threads)])

        env = self._build_password_env(password, storage_name or "default")
        if extra_env:
            env.update(extra_env)

        return await self.exec(args, repo_path, env=env, on_progress=on_progress, on_process_start=on_process_start)

    async def copy(
        self,
        repo_path: str,
        from_storage: str,
        to_storage: str,
        password: Optional[str] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        extra_env: Optional[Dict[str, str]] = None,
        on_process_start: Optional[Callable[[Any], None]] = None,
    ):
        args = ["copy", "-from", from_storage, "-to", to_storage]
        env = self._build_password_env(password, to_storage or "default")
        if extra_env:
            env.update(extra_env)
        return await self.exec(args, repo_path, env=env, on_progress=on_progress, on_process_start=on_process_start)

    async def list_snapshots(
        self,
        repo_path: str,
        password: Optional[str] = None,
        storage_name: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None,
        all_ids: bool = False,
    ):
        args = ["list"]
        if all_ids:
            args.append("-a")
        if storage_name:
            args.extend(["-storage", storage_name])
        env = self._build_password_env(password, storage_name or "default")
        if extra_env:
            env.update(extra_env)

        result = await self.exec(args, repo_path, env=env)
        result["snapshots"] = self._parse_list_output(result["stdout"])
        return result

    async def list_files(
        self,
        repo_path: str,
        revision: int,
        password: Optional[str] = None,
        storage_name: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None,
    ):
        args = ["list", "-files", "-r", str(revision)]
        if storage_name:
            args.extend(["-storage", storage_name])
        env = self._build_password_env(password, storage_name or "default")
        if extra_env:
            env.update(extra_env)

        result = await self.exec(args, repo_path, env=env)
        result["files"] = self._parse_file_list_output(result["stdout"])
        return result

    async def restore(
        self,
        repo_path: str,
        revision: int,
        overwrite: bool = True,
        password: Optional[str] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        storage_name: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None,
        patterns: Optional[List[str]] = None,
        threads: Optional[int] = None,
    ):
        args = ["restore", "-r", str(revision)]
        if storage_name:
            args.extend(["-storage", storage_name])
        if threads:
            args.extend(["-threads", str(threads)])
        if overwrite:
            args.append("-overwrite")
        if patterns:
            args.extend(patterns)

        env = self._build_password_env(password, storage_name or "default")
        if extra_env:
            env.update(extra_env)

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

    def _parse_file_list_output(self, stdout: str) -> List[Dict[str, Any]]:
        files: List[Dict[str, Any]] = []
        # Newer format: <size> <date> <time> <hash> <path>
        file_line_regex_with_hash = re.compile(
            r"^\s*\d+\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+[0-9a-f]{32,128}\s+(.+)$",
            re.IGNORECASE,
        )
        # Older format: <size> <date> <time> <path>   (no hash column)
        file_line_regex_no_hash = re.compile(
            r"^\s*\d+\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+(.+)$",
            re.IGNORECASE,
        )
        for raw in stdout.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.lower().startswith("snapshot "):
                continue
            if line.lower().startswith("listing "):
                continue
            if line.lower().startswith("storage set to"):
                continue
            if line.lower().startswith("files:"):
                continue
            if line.lower().startswith("total size:"):
                continue
            if line.lower().startswith("listing all chunks"):
                continue
            if line.lower().startswith("chunks:"):
                continue
            if line.startswith("OPTIONS:") or line.startswith("USAGE:"):
                continue

            # Formato típico de `duplicacy list -files`:
            # <size> <yyyy-mm-dd> <hh:mm:ss> <hash> <path>
            candidate = line
            match = file_line_regex_with_hash.match(line)
            if match and match.group(1).strip():
                candidate = match.group(1).strip()
            else:
                match_no_hash = file_line_regex_no_hash.match(line)
                if match_no_hash and match_no_hash.group(1).strip():
                    candidate = match_no_hash.group(1).strip()
                else:
                # Fallback conservador: tomar la parte tras la última secuencia hash larga.
                    fallback = re.match(r"^.*\s([0-9a-f]{32,128})\s+(.+)$", line, re.IGNORECASE)
                    if fallback and fallback.group(2).strip():
                        candidate = fallback.group(2).strip()

            # Ignore non-path summary-ish rows that still slip through
            lowered_candidate = candidate.lower()
            if lowered_candidate.startswith("snapshot ") or lowered_candidate.startswith("total size:"):
                continue

            files.append({
                "path": candidate,
                "raw": line,
                "isDir": candidate.endswith("/") or candidate.endswith("\\"),
            })

        # Dedupe por path preservando orden
        seen = set()
        unique_files = []
        for item in files:
            p = item["path"]
            if p in seen:
                continue
            seen.add(p)
            unique_files.append(item)
        return unique_files

# Singleton
service = DuplicacyService()
