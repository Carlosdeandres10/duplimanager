from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class RepoCreate(BaseModel):
    name: str
    path: str
    snapshotId: str
    importExisting: Optional[bool] = False
    storageId: Optional[str] = None
    destinationType: Optional[str] = "local"  # local | wasabi
    storageUrl: Optional[str] = None  # legacy single-destination field
    localStoragePath: Optional[str] = None
    wasabiEnabled: Optional[bool] = False
    wasabiEndpoint: Optional[str] = None
    wasabiRegion: Optional[str] = None
    wasabiBucket: Optional[str] = None
    wasabiDirectory: Optional[str] = None
    wasabiAccessId: Optional[str] = None
    wasabiAccessKey: Optional[str] = None
    password: Optional[str] = None
    encrypt: Optional[bool] = None
    contentSelection: Optional[List[str]] = None
    schedule: Optional[Dict[str, Any]] = None

class BackupStart(BaseModel):
    repoId: str
    password: Optional[str] = None
    threads: Optional[int] = None
    trigger: Optional[str] = None  # manual | scheduler

class BackupCancelRequest(BaseModel):
    repoId: str

class RestoreRequest(BaseModel):
    repoId: str
    revision: int
    overwrite: Optional[bool] = True
    password: Optional[str] = None
    storageName: Optional[str] = None
    restorePath: Optional[str] = None
    patterns: Optional[List[str]] = None

class StorageRestoreRequest(BaseModel):
    storageId: str
    snapshotId: str
    revision: int
    overwrite: Optional[bool] = True
    password: Optional[str] = None
    restorePath: Optional[str] = None
    patterns: Optional[List[str]] = None

class WasabiConnectionTest(BaseModel):
    endpoint: str
    region: str
    bucket: str
    accessId: str
    accessKey: str

class WasabiSnapshotDetectRequest(BaseModel):
    endpoint: str
    region: str
    bucket: str
    directory: Optional[str] = None
    accessId: str
    accessKey: str
    password: Optional[str] = None

class RepoUpdate(BaseModel):
    name: Optional[str] = None
    path: Optional[str] = None
    snapshotId: Optional[str] = None
    destinationType: Optional[str] = None  # local | wasabi
    localStoragePath: Optional[str] = None
    wasabiEndpoint: Optional[str] = None
    wasabiRegion: Optional[str] = None
    wasabiBucket: Optional[str] = None
    wasabiDirectory: Optional[str] = None
    wasabiAccessId: Optional[str] = None
    wasabiAccessKey: Optional[str] = None
    contentSelection: Optional[List[str]] = None
    schedule: Optional[Dict[str, Any]] = None

class StorageCreate(BaseModel):
    name: str
    type: str  # local | wasabi
    localPath: Optional[str] = None
    endpoint: Optional[str] = None
    region: Optional[str] = None
    bucket: Optional[str] = None
    directory: Optional[str] = None
    accessId: Optional[str] = None
    accessKey: Optional[str] = None
    duplicacyPassword: Optional[str] = None

class StorageUpdate(BaseModel):
    name: Optional[str] = None
    localPath: Optional[str] = None
    endpoint: Optional[str] = None
    region: Optional[str] = None
    bucket: Optional[str] = None
    directory: Optional[str] = None
    accessId: Optional[str] = None
    accessKey: Optional[str] = None
    duplicacyPassword: Optional[str] = None
    clearDuplicacyPassword: Optional[bool] = False
