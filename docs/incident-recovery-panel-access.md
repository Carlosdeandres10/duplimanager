# Recuperacion de acceso al panel (operativa)

## Objetivo
Restaurar el acceso al panel web cuando se olvida la contraseña local, sin introducir backdoors web ni codigos universales.

## Principios
- No existe codigo universal.
- No existe endpoint web de reset de contraseña.
- La recuperacion requiere acceso administrativo al servidor Windows (mantenimiento local).
- Todo cambio debe quedar auditado en logs.

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
- Ejecutar el procedimiento interno de mantenimiento local (script/CLI del equipo de soporte).
- Accion esperada:
  - desactivar temporalmente `panelAccess.enabled`
  - opcionalmente borrar `passwordBlob` si se necesita reset completo

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

## Estado actual del producto
- Ya existe auditoria de auth (login ok/fallo/bloqueo/logout/cambios de proteccion).
- Pendiente recomendado:
  - herramienta local de mantenimiento (CLI) formalizada para soporte
  - forzado explicito de cambio de contraseña post-recuperacion
