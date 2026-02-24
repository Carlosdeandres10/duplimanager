# Contrato IA: Notificaciones (Healthchecks / Email)

## Objetivo
Definir reglas minimas y estables para que la IA mantenga las notificaciones sin romper comportamientos ni generar falsos positivos.

## Terminos
- `Tipos de notificacion`: `healthchecks` (HTTP) y `email` (SMTP).
- `Configuracion global`: ajustes por defecto y pruebas de canal. No activa envios.
- `Configuracion por backup`: activa/desactiva cada tipo de notificacion y define overrides.

## Regla principal (activacion)
- La activacion de notificaciones se decide **solo por backup**.
- La configuracion global **no activa** envios por si sola.
- La configuracion global aporta:
  - parametros por defecto (URL/keyword/timeout)
  - SMTP global (host, puerto, auth, from)
  - botones de prueba independientes

## Reglas de guardado por backup
Si ambos tipos de notificacion estan desactivados:
- Se puede guardar aunque haya campos rellenos.

Si `Healthchecks para este backup` esta activado:
- Son obligatorios:
  - `URL Healthchecks (override)`
  - `Palabra de exito (override)`

Si `Email para este backup` esta activado:
- Son obligatorios:
  - `Email destino (override)`
  - `Palabra de exito (override)`

Notas:
- Los campos pueden permanecer rellenos aunque el checkbox este desactivado.
- El estado `enabled` se guarda segun el checkbox (no por tener texto en los campos).

## Reglas de envio (runtime)
- En backup exitoso, cada tipo de notificacion se envia solo si ese backup tiene `enabled=true`.
- SMTP siempre viene de configuracion global.
- `Email destino` y `Prefijo asunto` pueden venir por backup (override).
- `URL Healthchecks`, `keyword`, `sendLog` pueden venir por backup (override).

## Regla anti falsos positivos (Healthchecks)
- El body de prueba/envio debe contener **solo** la palabra configurada como senal (keyword).
- No se debe inyectar `success` fijo si el usuario ha configurado otra palabra (`error`, `exito`, etc.).
- Evitar texto interno que contenga `success` por accidente en body/subject cuando el keyword configurado no es `success`.

## Pruebas (UI)
### Configuracion (global)
- `Probar Healthchecks`: prueba solo HTTP.
- `Probar Email`: prueba solo SMTP/correo.
- Estas pruebas no deben depender de checkboxes globales de activacion (no existen).

### Editar Backup
- `Probar notificaciones` prueba envio real usando:
  - overrides del backup (si existen en el formulario)
  - SMTP global
- Debe mostrar resultado por tipo:
  - `Healthchecks OK/ERROR/omitido`
  - `Email OK/ERROR/omitido`

## Checklist de validacion (manual)
Antes de dar por buena una modificacion en notificaciones, comprobar:

1. Guardado por backup
- Activar Healthchecks sin URL -> error al guardar
- Activar Healthchecks sin keyword -> error al guardar
- Activar Email sin destino -> error al guardar
- Activar Email sin keyword -> error al guardar
- Desactivar un tipo y guardar -> queda desactivado al reabrir el modal

2. Herencia global vs backup
- Global con SMTP configurado + backup con Email desactivado -> no se envia email
- Global con URL Healthchecks + backup con Healthchecks activado y URL propia -> usa la URL del backup

3. Healthchecks sin falsos positivos
- `Success keywords = success` en Healthchecks
- Prueba desde backup con keyword `error`
- Confirmar que el body NO contiene `success` y el check no sube a OK

4. Pruebas separadas
- `Probar Healthchecks` funciona sin enviar email
- `Probar Email` funciona sin ping HTTP

## Checklist de validacion (tecnico)
- `python -m py_compile server_py/services/notifications.py server_py/routers/backups.py server_py/routers/system.py`
- `node --check web/js/modules/views/repositories.js`
- `node --check web/js/modules/views/settings.js`
- `node --check web/js/api.js`

## Regla de cambios futuros
Si se anade un nuevo tipo de notificacion (ej. Telegram, Slack):
- mantener el mismo modelo:
  - config global = transporte/defaults/prueba
  - backup = activacion + overrides + validacion
- actualizar este contrato y el checklist.
