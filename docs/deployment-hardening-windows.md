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

2. Instalador y servicio Windows
- Instalar con el instalador cliente (Inno Setup) como administrador.
- El instalador cliente registra un servicio Windows `DupliManager` usando WinSW (arranque automatico recomendado).
- Verificar en `services.msc`:
  - estado `En ejecución`
  - inicio `Automático`
- El acceso directo principal abre el panel web (`http://127.0.0.1:8500`) y no debe usarse para arrancar una segunda instancia manual.

3. Usuario de servicio
- Definir si se deja `LocalSystem` (inicio rapido) o una cuenta dedicada (recomendado en clientes con politicas de seguridad).
- Si se usa cuenta dedicada:
  - permisos de lectura en origenes de backup
  - permisos de escritura en destinos locales (si aplica)
  - acceso a rutas de red/SMB (si aplica)
- Si se quiere usar auto-descarga de `duplicacy.exe`, permitir salida HTTPS a `github.com` / `api.github.com` (solo primer uso si falta el binario).
- Minimizar permisos en disco a rutas de trabajo.

4. Red
- No exponer puerto del backend directamente a Internet.
- Firewall local: permitir solo origenes necesarios.
- Si hay proxy, pasar `X-Forwarded-Proto` correctamente para cookies seguras en modo `auto`.
- CORS:
  - mantener deshabilitado por defecto (same-origin)
  - si se habilita, usar solo `allowOrigins` explicitos (sin `*`)

5. Panel web
- Activar contraseña del panel.
- Importante UX: la contraseña del panel se guarda con el boton especifico `Guardar contraseña del panel` (no con `Guardar Configuración`).
- Configurar `cookieSecureMode = auto` (o `always` si siempre hay HTTPS).
- Ajustar TTL de sesion segun politica del cliente.
- Verificar la version mostrada en el footer tras upgrades.
- Verificar el enlace `Manual de usuario` desde el footer.
- Si se usa el aviso de updates:
  - comprobar acceso a `latest.json`
  - confirmar que la URL de updates queda correcta
- Revisar `Configuración -> Rutas del sistema (diagnóstico)` para confirmar:
  - `dataDir`, `configDir`, `logsDir`
  - ruta de `duplicacy.exe`
  - modo empaquetado (`frozen`)

6. Secrets
- Credenciales Wasabi/SMTP deben quedar guardadas protegidas con DPAPI tras su guardado.
- Revisar que no se exportan por UI/API/logs.
- Tras actualizar desde versiones legacy, ejecutar migracion activa de secretos:
  - `POST /api/system/migrate-secrets` (autenticado en panel)

7. Operacion
- Verificar logs (`AuthAudit`, backups, restore).
- Documentar procedimiento de recuperacion local de acceso.
- Backup de `config/duplimanager.db` y carpeta `logs/` segun politica.
- La herramienta `server_py.tools.maintenance` se considera tooling interno de soporte (no distribuir al cliente final).
- Si se usa canal de updates en Wasabi, aplicar policy pública solo al prefijo de releases (no al bucket de backups de clientes).

## Checklist de validacion post-instalacion
1. Abrir panel localmente -> OK
2. Login panel correcto -> OK
3. Intentos fallidos repetidos -> bloquea temporalmente (rate limit)
4. Guardar ajustes de seguridad (`host`, cookie, TTL) -> persiste
5. Crear/probar storage Wasabi -> OK
6. Backup y restore MVP -> OK (sin romper flujo Duplicacy)
7. Reiniciar servidor Windows (o servicio) y verificar que DupliManager vuelve a levantar solo -> OK
8. Comprobar `GET /api/system/update-check` -> sin error (si updates habilitado) -> OK

## Notas
- Cambios de `host` y `port` requieren reinicio del servicio.
- Si se usa proxy HTTPS, validar que la app recibe `X-Forwarded-Proto: https`.
- Cambios de `settings.cors` requieren reinicio del servicio (middleware se aplica al arrancar).
- En builds empaquetadas, los datos (`config/`, `logs/`) deben vivir fuera de `_internal`; comprobarlo en la tarjeta de rutas del panel.
