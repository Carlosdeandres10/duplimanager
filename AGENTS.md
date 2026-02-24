# AGENTS.md (Repositorio DupliManager)

## Objetivo
Este repositorio se mantiene con apoyo de IA. Antes de tocar flujos funcionales, la IA debe consultar contratos cortos y ejecutar pruebas mínimas.

## Contratos (lectura obligatoria por dominio)
- Notificaciones: `docs/notifications-contract.md`
- Backups: `docs/backups-contract.md`
- Restore: `docs/restore-contract.md`

## Regla de trabajo (cambios funcionales)
1. Leer el contrato del dominio afectado.
2. Hacer el cambio mínimo.
3. Ejecutar las pruebas mínimas del dominio.
4. Validar sintaxis backend/frontend si toca JS o Python.
5. Solo entonces responder como “corregido”.

## Pruebas MVP (comando)
```powershell
python -m unittest discover -s tests -v
```

## Validaciones de sintaxis (según cambio)
- Backend:
```powershell
python -m py_compile server_py/routers/backups.py server_py/routers/restore.py server_py/routers/system.py server_py/services/notifications.py
```
- Frontend:
```powershell
node --check web/js/modules/views/repositories.js
node --check web/js/modules/views/restore.js
node --check web/js/modules/views/settings.js
node --check web/js/api.js
```

## Regla de seguridad
- No romper compatibilidad del flujo Duplicacy:
  - `Storage -> Backup ID (Snapshot ID) -> Revision -> Restore`

