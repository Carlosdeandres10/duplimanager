# Despliegue y Hardening (Windows)

## Objetivo
Checklist operativo para instalaciones nuevas de DupliManager en servidores Windows.

## Recomendado por defecto
- `host = 127.0.0.1`
- Publicacion remota solo mediante:
  - VPN
  - reverse proxy con HTTPS
  - firewall allowlist

## Checklist de instalacion
1. Sistema operativo
- Windows actualizado (parches de seguridad).
- RDP protegido (MFA / acceso restringido).

2. Usuario de servicio
- Ejecutar DupliManager con usuario de servicio dedicado (no admin si no es necesario).
- Minimizar permisos en disco a rutas de trabajo.

3. Red
- No exponer puerto del backend directamente a Internet.
- Firewall local: permitir solo origenes necesarios.
- Si hay proxy, pasar `X-Forwarded-Proto` correctamente para cookies seguras en modo `auto`.
- CORS:
  - mantener deshabilitado por defecto (same-origin)
  - si se habilita, usar solo `allowOrigins` explicitos (sin `*`)

4. Panel web
- Activar contraseña del panel.
- Configurar `cookieSecureMode = auto` (o `always` si siempre hay HTTPS).
- Ajustar TTL de sesion segun politica del cliente.

5. Secrets
- Credenciales Wasabi/SMTP deben quedar guardadas protegidas con DPAPI tras su guardado.
- Revisar que no se exportan por UI/API/logs.
- Tras actualizar desde versiones legacy, ejecutar migracion activa de secretos:
  - `POST /api/system/migrate-secrets` (autenticado en panel)

6. Operacion
- Verificar logs (`AuthAudit`, backups, restore).
- Documentar procedimiento de recuperacion local de acceso.
- Backup de `config/duplimanager.db` y carpeta `logs/` segun politica.
- La herramienta `server_py.tools.maintenance` se considera tooling interno de soporte (no distribuir al cliente final).

## Checklist de validacion post-instalacion
1. Abrir panel localmente -> OK
2. Login panel correcto -> OK
3. Intentos fallidos repetidos -> bloquea temporalmente (rate limit)
4. Guardar ajustes de seguridad (`host`, cookie, TTL) -> persiste
5. Crear/probar storage Wasabi -> OK
6. Backup y restore MVP -> OK (sin romper flujo Duplicacy)

## Notas
- Cambios de `host` y `port` requieren reinicio del servicio.
- Si se usa proxy HTTPS, validar que la app recibe `X-Forwarded-Proto: https`.
- Cambios de `settings.cors` requieren reinicio del servicio (middleware se aplica al arrancar).
