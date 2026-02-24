# Contrato IA: Backups (MVP)

## Conceptos
- `Storage`: destino (Wasabi/local/...).
- `Backup ID (Snapshot ID)`: identificador del conjunto de revisiones en Duplicacy.
- `Backup` (en la UI): trabajo local que une `Directory + Storage + Backup ID`.

## Reglas
- Un backup siempre debe apuntar a un `Storage`.
- La UI de nuevo backup debe priorizar:
  1. `Directory`
  2. `Storage`
  3. `Backup ID (Snapshot ID)`
- El `Backup ID` puede ser:
  - nuevo (crear historial)
  - existente (vincular a historial ya presente en el storage)

## Notificaciones (relación con backups)
- La activación de notificaciones ocurre solo por backup.
- La configuración global aporta defaults + SMTP + pruebas.

## Validación mínima
- Si se activa Healthchecks por backup -> URL + keyword obligatorios.
- Si se activa Email por backup -> email destino + keyword obligatorios.

## Checklist manual
1. Crear backup con storage seleccionado y Backup ID nuevo -> guarda.
2. Vincular backup con Backup ID existente -> guarda.
3. Editar backup y desactivar notificaciones -> persiste desactivado.
4. Ejecutar backup -> logs y progreso visibles.

