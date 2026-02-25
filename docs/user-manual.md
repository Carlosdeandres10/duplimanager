# Manual de Usuario (DupliManager)

## Objetivo
Guía práctica para instalar, configurar y usar DupliManager sin entrar en detalles técnicos de desarrollo.

> Este manual está pensado para administradores o técnicos de cliente que gestionan copias de seguridad desde el panel web.

## 1. Primer arranque

### Qué hace DupliManager
DupliManager es un panel web que usa `duplicacy.exe` por debajo para:
- crear copias de seguridad (backups),
- programarlas,
- restaurar revisiones anteriores,
- revisar logs y estado del sistema.

### Instalación (Windows)
1. Ejecuta el instalador de DupliManager como administrador.
2. El instalador crea un servicio Windows `DupliManager`.
3. Al terminar, abre el panel en:
   - `http://127.0.0.1:8500`

### Comprobación inicial
En el footer izquierdo debes ver:
- `Servidor activo` (verde)

Si no aparece, revisa el servicio en `services.msc`.

**Captura sugerida:** Dashboard con footer (`Servidor activo`)  
[Captura: Dashboard]

## 2. Navegación del panel

Menú lateral principal:
- `Dashboard`: resumen de backups y accesos rápidos
- `Repositorios`: destinos de copia (Wasabi/local)
- `Backups`: tareas de copia
- `Tareas`: programación y ejecución automática
- `Restaurar`: recuperación de datos
- `Configuración`: ajustes globales
- `Logs`: registros del sistema

## 3. Crear un repositorio (destino)

Un repositorio es el destino donde se guardarán las copias (por ejemplo Wasabi o una ruta local).

### Repositorio local
1. Ve a `Repositorios`.
2. Pulsa `Nuevo Repositorio`.
3. Selecciona `Tipo de destino = Local`.
4. Escribe la ruta del storage (ejemplo: `D:\Backups\duplicacy-storage`).
5. Pulsa `Guardar Repositorio`.

### Repositorio Wasabi
1. Ve a `Repositorios`.
2. Pulsa `Nuevo Repositorio`.
3. Selecciona `Tipo de destino = Wasabi S3`.
4. Rellena:
   - Endpoint Wasabi
   - Región
   - Bucket
   - Directorio (opcional)
   - `Access ID`
   - `Access Key`
   - (opcional) contraseña Duplicacy para cifrado
5. Guarda.

**Capturas sugeridas:** lista de repositorios y modal “Nuevo Repositorio”  
[Captura: Repositorios]  
[Captura: Nuevo Repositorio]

## 4. Crear un backup

1. Ve a `Backups` o pulsa `Nuevo Backup`.
2. Selecciona la carpeta a respaldar (o escribe la ruta manualmente).
3. Elige el repositorio de destino.
4. Define la configuración del backup:
   - `Nuevo (Desde cero)` o continuar con uno existente
   - `Backup ID (Snapshot ID)` (si quieres continuidad del histórico)
5. (Opcional) Configura:
   - filtros de contenido,
   - notificaciones Healthchecks,
   - email por backup (override del global).
6. Pulsa `Verificar Configuración`.
7. Pulsa `Crear Backup`.

### Importante: Backup ID (Snapshot ID)
- Si reutilizas el mismo `Backup ID`, Duplicacy continúa el histórico (incremental a nivel de chunks).
- Si quieres separar historiales, usa un ID nuevo.

**Capturas sugeridas:** modal “Nuevo Backup” (parte superior e inferior)  
[Captura: Nuevo Backup - formulario]  
[Captura: Nuevo Backup - opciones y creación]

## 5. Ejecutar backups y programarlos

### Ejecutar ahora
En `Dashboard` o `Tareas`, usa el botón:
- `Backup` / `Ahora`

### Programación
En `Tareas` puedes:
- activar/desactivar tareas,
- lanzar `Ahora`,
- pausar,
- editar programación.

**Captura sugerida:** pantalla `Tareas programadas`  
[Captura: Tareas]

## 6. Restaurar archivos y carpetas

1. Ve a `Restaurar`.
2. Selecciona:
   - `Destino de copias (Storage)`
   - `Backup ID (Snapshot ID)`
3. (Opcional) Indica `Ruta de restauración`.
4. Pulsa `Cargar revisiones`.
5. Elige una revisión.
6. Selecciona:
   - restaurar todo el snapshot, o
   - restauración parcial (selección de contenido)
7. Pulsa `Restaurar`.

### Durante la restauración
- Verás el `Log de restauración` en vivo.
- El botón cambia a `⏹ Terminar` mientras se ejecuta.
- Al acabar, podrás pulsar `✅ Finalizar` para limpiar la vista.

### Nota sobre la carpeta `.duplicacy`
Si restauras en una carpeta nueva, DupliManager puede crear `.duplicacy` para inicializar la ruta.  
Si restauras varias veces en la misma carpeta y la configuración coincide, la app reutiliza esa configuración.

**Captura sugerida:** pantalla `Restaurar` con log y estado  
[Captura: Restaurar]

## 7. Configuración global

En `Configuración` puedes ajustar:
- ruta de `Duplicacy CLI`,
- host/puerto del panel,
- idioma/tema,
- opciones de seguridad del panel,
- notificaciones (Healthchecks / Email),
- migración de secretos legacy a DPAPI,
- diagnóstico de rutas del sistema.

**Capturas sugeridas:** configuración general, rutas y seguridad  
[Captura: Configuración - general]  
[Captura: Configuración - rutas]  
[Captura: Configuración - acceso al panel]

## 8. Protección del panel (contraseña local)

### Cómo activarla correctamente
1. Ve a `Configuración` -> `Acceso al panel (contraseña local)`.
2. Marca `Requerir contraseña para acceder al panel web`.
3. Escribe:
   - `Nueva contraseña`
   - `Confirmar nueva contraseña`
4. Pulsa **`🔐 Guardar contraseña del panel`**.

### Importante (muy común)
El botón `💾 Guardar Configuración` **NO guarda la contraseña del panel**.  
La contraseña del panel se guarda con su botón específico:
- `🔐 Guardar contraseña del panel`

### Cómo comprobarlo
En el footer izquierdo debe aparecer:
- `Panel protegido`

## 9. Notificaciones (Healthchecks y Email)

### Healthchecks (global)
Configurable en `Configuración`:
- URL
- palabra de éxito
- timeout
- incluir log del backup

Puedes probarlo con:
- `Probar Healthchecks`

### Email (global)
Configurable en `Configuración`:
- servidor SMTP
- puerto
- STARTTLS
- usuario/contraseña
- remitente/destino
- prefijo de asunto
- incluir log en email

Puedes probarlo con:
- `Probar Email`

## 10. Logs del sistema

En `Logs` puedes:
- elegir archivo de log,
- filtrar por texto,
- nivel,
- tipo,
- rango de fechas,
- exportar filtrado.

Útil para soporte y auditoría:
- eventos de login (`AuthAudit`)
- ejecuciones del scheduler
- errores de backup/restore

**Captura sugerida:** pantalla `Logs del Sistema`  
[Captura: Logs]

## 11. Actualizaciones de DupliManager

Cuando hay una versión nueva publicada:
- DupliManager muestra un aviso en el footer:
  - `Nueva versión X.Y.Z · Descargar`

### Flujo recomendado
1. Descarga el instalador desde el enlace del aviso.
2. Ejecuta el instalador como administrador.
3. Instala/actualiza.
4. Abre el panel y verifica la versión en el footer.

### Nota
- La URL de actualizaciones (`latest.json`) está gestionada por Caisoft.

## 12. Solución rápida de problemas

### No arranca el panel
1. Revisar servicio `DupliManager` en `services.msc`
2. Verificar puerto `8500`
3. Consultar `Logs`

### No detecta actualizaciones
1. Verificar acceso a Internet del servidor
2. Comprobar `latest.json` en la URL configurada
3. Recargar la app (`Ctrl+F5`)

### No puedo elegir carpetas con el botón “Seleccionar”
En instalaciones de servidor empaquetadas, el selector visual puede estar deshabilitado.  
Escribe la ruta manualmente en el campo.

## 13. Manual técnico (para soporte/administración avanzada)

Para detalles técnicos (instalador, WinSW, seguridad, releases, Wasabi, hardening):
- `docs.html`
- `docs/windows-packaging.md`
- `docs/deployment-hardening-windows.md`
- `docs/security-plan.md`

