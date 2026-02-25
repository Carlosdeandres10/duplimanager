# Plan de Securizacion (DupliManager)

## Objetivo
Endurecer DupliManager para despliegues reales en multiples servidores Windows, sin frenar el desarrollo funcional.

## Modelo de amenaza (realista)
### Amenazas que SI queremos cubrir
- Atacantes de red contra el panel web/API (puerto del servicio).
- Robo de `duplimanager.db` o archivos de configuracion/logs.
- Errores operativos de clientes (exposicion accidental del panel, contraseñas olvidadas, configuraciones inseguras por defecto).

### Amenazas que NO cubrimos completamente
- Atacante con control administrativo del servidor Windows (RDP/shell como admin o equivalente al usuario del servicio).

Nota:
- En ese escenario, el host se considera comprometido y la seguridad pasa a depender principalmente de Windows, segmentacion, MFA, VPN, hardening y monitorizacion.

## Principios de diseno
- Defaults seguros por defecto.
- No exponer secretos por API/UI/logs.
- Secretos cifrados en reposo (DPAPI) cuando sea viable.
- Compatibilidad con flujos Duplicacy:
  - `Storage -> Backup ID (Snapshot ID) -> Revision -> Restore`
- Cambios incrementales con pruebas MVP + validaciones de sintaxis.

## Estado base (analisis inicial)
- Tests MVP: OK (`python -m unittest discover -s tests -v`)
- Sintaxis Python/JS: OK (routers y vistas clave)
- Riesgos principales detectados:
  - API bind en `0.0.0.0` por defecto
  - CORS abierto `*`
  - Login del panel sin rate limiting/lockout
  - Cookie de sesion del panel con `secure=False`
  - Secretos (Wasabi/SMTP) en claro en config/SQLite
  - Endpoints de logs con validacion de filename insuficiente (riesgo de path traversal)

## Fases de trabajo (orden recomendado)
### Fase 1 - Hardening minimo obligatorio (alta prioridad)
Objetivo: reducir riesgo inmediato en instalaciones nuevas.

Tareas:
- Cambiar bind por defecto a `127.0.0.1` (opt-in para exponer red).
- Anadir configuracion para `secure cookies` cuando haya HTTPS.
- Anadir rate limit + lockout en `/api/auth/login`.
- Endurecer endpoints de logs validando `filename` (sin traversal).
- Anadir eventos de auditoria de auth (login/logout/reset/recovery).

Criterios de aceptacion:
- El panel no queda expuesto en red por defecto.
- Intentos repetidos de login se limitan/bloquean temporalmente.
- No se puede leer un archivo fuera de `logs/` via API de logs.

### Fase 2 - Proteccion de secretos (alta prioridad)
Objetivo: que robar la BBDD/archivos no exponga credenciales en claro.

Tareas:
- Cifrar con DPAPI:
  - credenciales Wasabi (`accessId`, `accessKey`)
  - `duplicacyPassword`
  - `smtpPassword`
- Migracion automatica de datos legacy (leer formato antiguo y reescribir cifrado).
- Mantener `sanitize_*` y APIs sin exponer secretos.
- Evitar backups JSON con secretos en claro (o guardarlos redactados/cifrados).

Criterios de aceptacion:
- `duplimanager.db` y `config/*.json` no contienen secretos legibles en texto plano.
- Los flujos de backup/restore/notifications siguen funcionando sin cambios en UI.

### Fase 3 - Recuperacion de acceso (operativa, sin backdoor web)
Objetivo: procedimiento de recuperacion controlado y documentado.

Decision actual:
- No usar codigo universal.
- No habilitar reset por endpoint web.
- No introducir (por ahora) sistema complejo de firmas de soporte.

Tareas:
- Documentar procedimiento local de mantenimiento (solo admin del servidor).
- Registrar auditoria del evento de recuperacion.
- Forzar cambio de contraseña del panel tras recuperacion (si aplica).

Criterios de aceptacion:
- Soporte puede recuperar acceso con procedimiento claro.
- No existe contraseña maestra compartida ni endpoint de recovery abierto.

### Fase 4 - Despliegue Windows a escala
Objetivo: instalaciones reproducibles y operables.

Tareas:
- Guia de hardening Windows (firewall, VPN/reverse proxy, TLS, usuario de servicio).
- Instalacion como servicio Windows (un proceso / un scheduler).
- Checklist post-instalacion.
- Backup/restore de configuracion (`duplimanager.db`) y logs.

Criterios de aceptacion:
- Instalacion estandarizada y repetible.
- Operacion y soporte documentados.

## Regla de ejecucion por cambio
1. Cambio minimo.
2. Pruebas MVP (`python -m unittest discover -s tests -v`).
3. Validacion sintaxis Python/JS si aplica.
4. Responder con estado y siguiente paso.

## Backlog corto (ejecucion inmediata)
1. Hardening logs API (`filename` seguro).
2. Rate limit de login panel.
3. Configuracion de bind seguro (`127.0.0.1` por defecto).
4. Flag/config para cookie `Secure`.
5. DPAPI para `smtpPassword` y secretos Wasabi (primera migracion).

## Avance implementado (fase 1)
### Hecho
- Hardening de lectura de logs por API (validacion de `filename` para evitar traversal).
- Bind por defecto del servidor en `127.0.0.1` (configurable por `settings.host`).
- Rate limit / lockout basico en login del panel por IP del cliente.
- Cookie de sesion con `Secure` configurable segun entorno HTTPS.
- Auditoria de eventos de auth (login OK/fallo/bloqueo, logout, cambios de proteccion del panel).
- Inicio de fase 2: secretos en reposo con DPAPI (compatibilidad legacy) para:
  - `notifications.email.smtpPassword`
  - credenciales de storages Wasabi (`accessId`, `accessKey`)
  - `duplicacyPassword` de storage y secretos de repo escritos desde altas nuevas

### Configuracion nueva (manual, hasta tener UI)
- `settings.panelAccess.cookieSecureMode`:
  - `"auto"` (recomendado): activa `Secure` si la request llega por HTTPS o `X-Forwarded-Proto: https`
  - `"always"`: fuerza `Secure=true`
  - `"never"`: fuerza `Secure=false` (solo entornos locales HTTP)
- `settings.panelAccess.sessionTtlSeconds`:
  - TTL de sesion del panel (deslizante), con rango seguro limitado por backend
- `settings.host`:
  - host de escucha del servidor (bind); recomendado `127.0.0.1`
  - cambiarlo requiere reiniciar el servicio

Ejemplo:
```json
{
  "panelAccess": {
    "cookieSecureMode": "auto"
  }
}
```

### UI (panel de Configuracion)
Ya se han anadido controles para administrador:
- `Host del Servidor (bind)` (`settings.host`)
- `Cookies seguras del panel` (`settings.panelAccess.cookieSecureMode`)
- `Expiracion sesion` (`settings.panelAccess.sessionTtlSeconds`)
- `Migrar secretos legacy a DPAPI` (dispara `POST /api/system/migrate-secrets`)

Nota operativa:
- `host` y `port` requieren reiniciar el servicio para aplicar.

### Notas de migracion de secretos (fase 2)
- Compatibilidad: si un secreto sigue en claro en SQLite/JSON, el sistema lo sigue leyendo.
- Migracion por escritura: al guardar `settings`, storages o crear backups nuevos, los secretos se reescriben protegidos con DPAPI (Windows).
- Migracion activa disponible: endpoint autenticado `POST /api/system/migrate-secrets` (ejecucion manual por admin desde panel/API).
- Falta pendiente:
  - evitar persistencia en claro en copias JSON de backup de config si quedan datos legacy no reescritos

### Documentacion operativa creada
- `docs/incident-recovery-panel-access.md`
- `docs/deployment-hardening-windows.md`
