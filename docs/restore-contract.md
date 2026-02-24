# Contrato IA: Restore (MVP)

## Flujo obligatorio (modelo Duplicacy)
El flujo de restauración debe seguir este orden:
1. `Storage` (destino donde están las copias)
2. `Backup ID (Snapshot ID)`
3. `Revision`
4. `Restore`

## Reglas
- No mezclar backups locales de otro storage en el selector de `Backup ID`.
- En storages remotos (Wasabi), los `Backup ID` deben venir del storage remoto (fuente de verdad).
- El `Backup local` solo puede aportar contexto (alias/ruta), no mezclar IDs ajenos.

## Rendimiento
- No cargar archivos de la revisión automáticamente al seleccionar revisión.
- Cargar contenido parcial solo bajo acción explícita (`Seleccionar contenido a restaurar`).
- Usar caché para `Backup IDs`, revisiones y ficheros cuando sea posible.

## Seguridad de restauración
- Si la carpeta destino contiene una `.duplicacy` de otro repo/storage, no reutilizarla silenciosamente.
- Debe informar error claro o exigir carpeta limpia.

## Checklist manual
1. Elegir storage Wasabi -> cargar Backup IDs remotos correctos.
2. Elegir Backup ID -> cargar revisiones.
3. Elegir revisión -> la UI no se congela.
4. Restaurar completo y parcial -> muestra progreso y log.

