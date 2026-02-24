# Testing MVP (DupliManager)

## Objetivo
Tener una base mínima de pruebas automáticas que cubra reglas de negocio críticas y reduzca regresiones al hacer cambios con IA.

## Qué cubre este MVP
- Notificaciones (reglas global vs por backup)
- Validación de notificaciones por backup
- Prevención de falsos positivos de Healthchecks por keyword

## Qué NO cubre aún
- Integración real con Duplicacy CLI
- UI end-to-end
- Restore remoto completo
- Scheduler completo

## Ejecutar pruebas
```powershell
python -m unittest discover -s tests -v
```

## Validaciones rápidas recomendadas tras cambios
```powershell
python -m py_compile server_py/routers/backups.py server_py/routers/system.py server_py/services/notifications.py
node --check web/js/modules/views/repositories.js
node --check web/js/modules/views/settings.js
```

## Próximas pruebas de alto valor (siguiente fase)
1. Restore: no mezclar `Backup ID` de distintos storages.
2. Restore: rechazo de carpeta destino con `.duplicacy` conflictiva.
3. Detección de `Snapshot IDs` remotos (`duplicacy list -a`) y caché.
4. Scheduler: disparo y logging de `queued/running/ok/error`.

