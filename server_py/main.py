import os
import uuid
import asyncio
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from server_py.utils.logger import get_logger, get_log_files, read_log_file
from server_py.utils import config_store
from server_py.services.duplicacy import service as duplicacy_service

# ─── CONFIG ───────────────────────────────────────────────
logger = get_logger("Server")
app = FastAPI(title="DupliManager API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── MODELS ───────────────────────────────────────────────
class RepoCreate(BaseModel):
    name: str
    path: str
    snapshotId: str
    storageUrl: str
    password: Optional[str] = None
    encrypt: Optional[bool] = True

class BackupStart(BaseModel):
    repoId: str
    password: Optional[str] = None

class RestoreRequest(BaseModel):
    repoId: str
    revision: int
    overwrite: Optional[bool] = True
    password: Optional[str] = None

# ─── STATE ────────────────────────────────────────────────
active_backups: Dict[str, Dict[str, Any]] = {}

# ─── API ROUTES ───────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }

# --- Repositories ---

@app.get("/api/repos")
async def get_repos():
    return {"ok": True, "repos": config_store.repositories.read()}

@app.post("/api/repos")
async def create_repo(repo: RepoCreate):
    repo_path = Path(repo.path)
    if not repo_path.exists():
        repo_path.mkdir(parents=True, exist_ok=True)

    result = await duplicacy_service.init(
        str(repo_path), 
        repo.snapshotId, 
        repo.storageUrl, 
        password=repo.password,
        encrypt=repo.encrypt if repo.encrypt is not None else (True if repo.password else False)
    )

    if result["code"] != 0:
        raise HTTPException(status_code=500, detail=result["stdout"] or "Duplicacy init failed")

    repos_data = config_store.repositories.read()
    new_repo = {
        "id": str(uuid.uuid4()),
        "name": repo.name,
        "path": str(repo_path),
        "snapshotId": repo.snapshotId,
        "storageUrl": repo.storageUrl,
        "encrypted": bool(repo.password),
        "createdAt": datetime.now().isoformat(),
        "lastBackup": None,
        "lastBackupStatus": None
    }
    repos_data.append(new_repo)
    config_store.repositories.write(repos_data)
    
    return {"ok": True, "repo": new_repo}

@app.delete("/api/repos/{repo_id}")
async def delete_repo(repo_id: str):
    repos_data = config_store.repositories.read()
    repo = next((r for r in repos_data if r["id"] == repo_id), None)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    repos_data = [r for r in repos_data if r["id"] != repo_id]
    config_store.repositories.write(repos_data)
    return {"ok": True, "removed": repo}

# --- Backup ---

@app.post("/api/backup/start")
async def start_backup(req: BackupStart, background_tasks: BackgroundTasks):
    repos_data = config_store.repositories.read()
    repo = next((r for r in repos_data if r["id"] == req.repoId), None)
    
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    if req.repoId in active_backups:
        raise HTTPException(status_code=409, detail="Backup already running")

    active_backups[req.repoId] = {
        "status": "running",
        "startedAt": datetime.now().isoformat(),
        "lastOutput": "Iniciando..."
    }

    async def run_backup_task():
        def on_progress(text):
            if req.repoId in active_backups:
                active_backups[req.repoId]["lastOutput"] = text.strip()

        result = await duplicacy_service.backup(
            repo["path"], 
            password=req.password,
            on_progress=on_progress
        )

        # Update repo info
        all_repos = config_store.repositories.read()
        for r in all_repos:
            if r["id"] == req.repoId:
                r["lastBackup"] = datetime.now().isoformat()
                r["lastBackupStatus"] = "success" if result["code"] == 0 else "error"
                r["lastBackupOutput"] = result["stdout"][-500:]
                break
        config_store.repositories.write(all_repos)
        
        del active_backups[req.repoId]

    background_tasks.add_task(run_backup_task)
    return {"ok": True}

@app.get("/api/backup/status/{repo_id}")
async def get_backup_status(repo_id: str):
    info = active_backups.get(repo_id)
    if not info:
        return {"ok": True, "running": False}
    return {"ok": True, "running": True, **info}

@app.get("/api/backup/progress/{repo_id}")
async def backup_progress(repo_id: str):
    async def event_generator():
        while True:
            info = active_backups.get(repo_id)
            if not info:
                yield f"data: {json.dumps({'done': True})}\n\n"
                break
            
            yield f"data: {json.dumps({'running': True, 'output': info.get('lastOutput', '')})}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# --- Snapshots & Restore ---

@app.get("/api/snapshots/{repo_id}")
async def list_snapshots(repo_id: str, password: Optional[str] = None):
    repos_data = config_store.repositories.read()
    repo = next((r for r in repos_data if r["id"] == repo_id), None)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
        
    result = await duplicacy_service.list_snapshots(repo["path"], password=password)
    return {"ok": True, "snapshots": result["snapshots"]}

@app.post("/api/restore")
async def restore(req: RestoreRequest):
    repos_data = config_store.repositories.read()
    repo = next((r for r in repos_data if r["id"] == req.repoId), None)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
        
    result = await duplicacy_service.restore(
        repo["path"], 
        req.revision, 
        overwrite=req.overwrite, 
        password=req.password
    )
    
    if result["code"] != 0:
        raise HTTPException(status_code=500, detail="Restore failed")
        
    return {"ok": True, "output": result["stdout"]}

# --- Config & Logs ---

@app.get("/api/config/settings")
async def get_settings():
    return {"ok": True, "settings": config_store.settings.read()}

@app.put("/api/config/settings")
async def update_settings(req: Request):
    data = await req.json()
    current = config_store.settings.read()
    current.update(data)
    config_store.settings.write(current)
    return {"ok": True, "settings": current}

@app.get("/api/config/logs")
async def list_logs():
    return {"ok": True, "files": get_log_files()}

@app.get("/api/config/logs/{filename}")
async def read_log(filename: str):
    content = read_log_file(filename)
    if content is None:
        raise HTTPException(status_code=404, detail="Log file not found")
    return {"ok": True, "content": content}

# --- Frontend Serving ---

from pathlib import Path
ROOT_DIR = Path(__file__).parent.parent
WEB_DIR = ROOT_DIR / "web"

app.mount("/css", StaticFiles(directory=str(WEB_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(WEB_DIR / "js")), name="js")

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    # Fallback to index.html for SPA routing
    return FileResponse(str(WEB_DIR / "index.html"))

# ─── MAIN ─────────────────────────────────────────────────
import uvicorn
import json

if __name__ == "__main__":
    settings_data = config_store.settings.read()
    port = settings_data.get("port", 8500)
    logger.info(f"🚀 DupliManager (Python) iniciando en http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
