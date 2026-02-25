# Recuperacion de acceso al panel (operativa)

## Objetivo
Restaurar el acceso al panel web cuando se olvida la contraseña local, sin introducir backdoors web ni codigos universales.

## Principios
- No existe codigo universal.
- No existe endpoint web de reset de contraseña.
- La recuperacion requiere acceso administrativo al servidor Windows (mantenimiento local).
- Todo cambio debe quedar auditado en logs.
- La herramienta CLI de mantenimiento es de uso interno del proveedor/soporte y no debe distribuirse a clientes.

## Modelo de seguridad
- Este procedimiento NO empeora el modelo real de amenaza:
  - un admin local del servidor ya puede modificar software/configuracion.
- El objetivo del panel sigue siendo:
  - proteger frente a atacantes de red
  - proteger secretos en reposo (DPAPI) frente a robo de BBDD/archivos

## Procedimiento (mantenimiento local)
1. Verificar incidencia
- Confirmar con el cliente que no puede acceder al panel por olvido de contraseña.
- Confirmar que se dispone de acceso administrativo al servidor Windows.

2. Parar el servicio de DupliManager
- Parar el servicio/proceso antes de tocar configuracion.

3. Resetear proteccion del panel (local)
- Ejecutar la herramienta local de mantenimiento (CLI interno de soporte) en el servidor.
- Accion esperada:
  - desactivar temporalmente `panelAccess.enabled`
  - opcionalmente borrar `passwordBlob` si se necesita reset completo

Ejemplos (PowerShell, uso interno de soporte):
```powershell
python -m server_py.tools.maintenance panel-auth-status
python -m server_py.tools.maintenance panel-auth-unlock
python -m server_py.tools.maintenance panel-auth-unlock --clear-password
```

4. Arrancar servicio
- Arrancar de nuevo DupliManager.

5. Reconfigurar de inmediato
- Entrar al panel.
- Definir nueva contraseña del panel.
- Revisar:
  - `cookieSecureMode`
  - expiracion de sesion
  - host/puerto

6. Registrar cierre de incidencia
- Documentar:
  - fecha/hora
  - servidor afectado
  - tecnico responsable
  - motivo (olvido de contraseña)

## Recomendaciones de operacion
- Mantener acceso al panel por `127.0.0.1` + VPN/reverse proxy.
- No exponer el puerto directamente a Internet.
- Usar contraseñas de panel fuertes y rotacion si cambia el personal.
- Revisar logs de `AuthAudit` tras incidencias.
- No desplegar ni publicar la herramienta de mantenimiento en instaladores de cliente (tooling interno).

## Estado actual del producto
- Ya existe auditoria de auth (login ok/fallo/bloqueo/logout/cambios de proteccion).
- Ya existe herramienta local de mantenimiento (CLI) para soporte.
- Pendiente recomendado:
  - forzado explicito de cambio de contraseña post-recuperacion
