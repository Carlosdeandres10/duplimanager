# Empaquetado Windows (Fase 1.5)

## Objetivo
Preparar builds reproducibles para Windows sin mezclar tooling interno de soporte con el binario de cliente.

## Alcance de esta fase (pre-empaquetado)
- `requirements-lock.txt` fijado para builds mas reproducibles.
- Tests de seguridad base (`tests/test_security_core.py`) incluidos.
- `pick-folder` deshabilitado en builds `frozen` (headless/servidor) para evitar fallos por `tkinter`.
- Scripts de build separados:
  - cliente (`scripts/build-client.ps1`)
  - soporte interno (`scripts/build-support-maintenance.ps1`)
- Exclusión explícita del CLI interno `server_py.tools.maintenance` en build de cliente.

## Requisitos previos (equipo de build)
1. Windows con PowerShell.
2. Python + entorno del proyecto (`.venv` recomendado).
3. Dependencias instaladas desde lock:
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
   .\.venv\Scripts\python.exe -m pip install pyinstaller
   ```
4. (Opcional) `bin\duplicacy.exe` presente si se quiere empaquetar el binario Duplicacy dentro de la build cliente.

## Comandos de build
### Build cliente (sin herramienta de mantenimiento interna)
```powershell
.\scripts\build-client.ps1
```

Opcional `onefile`:
```powershell
.\scripts\build-client.ps1 -OneFile
```

### Build soporte (CLI interno de mantenimiento)
Uso interno del proveedor/soporte. No distribuir al cliente.
```powershell
.\scripts\build-support-maintenance.ps1
```

## Instalador Windows (Inno Setup)
### Script base del instalador
- `installer/DupliManager.iss`

Características de esta base:
- Modo `client` y `support` con el mismo `.iss` (selector por macro `BuildMode`)
- Instalación por defecto en `C:\ProgramData\...` para evitar problemas de permisos con `config/logs`
- Excluye `server.log` si aparece en el árbol de `dist`
- Conserva datos de runtime en upgrades normales (no borra `config/logs` a la fuerza)
- En modo cliente instala y arranca servicio Windows usando **WinSW** (recomendado para scheduler/tareas programadas)

## Rutas runtime (importante para builds empaquetadas)
Se ha centralizado la resolución de rutas en:
- `server_py/utils/paths.py`

Objetivo:
- separar **recursos empaquetados** (`_internal`, assets web, librerías) de **datos de runtime** (`config`, `logs`, cache)
- evitar que upgrades rompan la persistencia
- facilitar soporte/diagnóstico en clientes

Resumen de comportamiento:
- Desarrollo (desde repo): datos y recursos salen del árbol del proyecto.
- Empaquetado (`frozen`): recursos desde `bundleDir` (`_internal`) y datos desde la raíz de instalación (`dataDir`, p.ej. `C:\ProgramData\DupliManager`).

Diagnóstico en panel:
- `Configuración -> Rutas del sistema (diagnóstico)` (solo lectura)
- API: `GET /api/system/paths`

### WinSW (servicio Windows)
Archivos de integración:
- `installer/winsw/DupliManagerService.xml` (config del servicio)
- `installer/vendor/winsw/WinSW-x64.exe` (binario WinSW, se renombra en instalación a `DupliManagerService.exe`)

Descarga rápida del binario WinSW:
```powershell
.\scripts\download-winsw.ps1
```

Descarga rápida de Duplicacy CLI (Windows x64):
```powershell
.\scripts\download-duplicacy.ps1 -Version latest -Arch x64
```

Notas:
- El instalador cliente falla con mensaje claro si no encuentra `installer/vendor/winsw/WinSW-x64.exe`.
- El servicio Windows permite que el scheduler interno de DupliManager siga ejecutando tareas programadas aunque nadie haya iniciado sesión.

### Compilar instalador con wrapper PowerShell
```powershell
.\scripts\build-installer.ps1 -Mode client -Version 1.0.0
```

Si quieres compilar primero PyInstaller y luego Inno en una sola orden:
```powershell
.\scripts\build-installer.ps1 -Mode client -Version 1.0.0 -BuildPyInstallerFirst
```

Build de soporte (CLI interno):
```powershell
.\scripts\build-installer.ps1 -Mode support -Version 1.0.0
```

El script intenta detectar `ISCC.exe` en:
- `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`
- `C:\Program Files\Inno Setup 6\ISCC.exe`

También admite ruta manual:
```powershell
.\scripts\build-installer.ps1 -Mode client -ISCCPath "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

## Automatización con GitHub (recomendado)
### Workflow CI/CD (Windows)
- `.github/workflows/release-windows-installer.yml`

Qué hace:
1. Prepara runner Windows
2. Instala Python + dependencias + PyInstaller
3. Instala Inno Setup 6
4. Descarga `WinSW` y `duplicacy.exe` (modo `client`)
5. Ejecuta pruebas MVP + validaciones de sintaxis
6. Genera build (`PyInstaller`) + instalador (`Inno Setup`)
7. Calcula `SHA256`
8. Genera `latest.json` (cliente) para comprobación de updates en panel
9. Publica artefactos en Wasabi (cliente, si hay secrets configurados)
10. Publica artefactos y (si hay tag `v*`) crea/actualiza GitHub Release

### Disparadores
- `push` a tags `v*` (publica Release)
- `workflow_dispatch` (manual; puede compilar cliente/soporte y opcionalmente publicar Release)

### Flujo recomendado de publicación
1. Commit/push a `main`
2. Crear tag:
   ```powershell
   git tag v1.0.1
   git push origin v1.0.1
   ```
3. Esperar workflow `Release Windows Installer`
4. Descargar el `.exe` desde GitHub Releases

### Repositorio privado + distribución a clientes (recomendado)
Si el repositorio de GitHub es privado:
- **GitHub Releases** sirve para CI/CD interno y control del equipo.
- **Clientes** deberían descargar desde un canal externo (ej. Wasabi) para no requerir acceso al repo.

Canal recomendado:
- `WASABI_PUBLIC_BASE_URL/latest.json`
- instaladores y artefactos en Wasabi bajo un prefijo versionado.

## Publicación de updates en Wasabi (`latest.json`)
El workflow puede publicar el instalador de cliente y los metadatos de actualización en Wasabi (S3 compatible).

### Secrets de GitHub Actions requeridos
- `WASABI_ACCESS_KEY_ID`
- `WASABI_SECRET_ACCESS_KEY`
- `WASABI_BUCKET`
- `WASABI_ENDPOINT` (ej. `https://s3.eu-central-1.wasabisys.com`)
- `WASABI_REGION` (ej. `eu-central-1`)
- `WASABI_RELEASES_PREFIX` (ej. `duplimanager/client`)
- `WASABI_PUBLIC_BASE_URL` (ej. `https://duplimanager.s3.eu-central-1.wasabisys.com/duplimanager/client`)

### Artefactos publicados en Wasabi (cliente)
Raíz del canal (`<prefix>/`):
- `latest.json`
- `DupliManager-client-setup-x.y.z.exe`
- `SHA256SUMS.txt`
- `release-metadata.json`
- `release-notes.md`

Carpeta versionada (`<prefix>/<version>/`):
- `DupliManager-client-setup-x.y.z.exe`
- `SHA256SUMS.txt`
- `release-metadata.json`
- `release-notes.md`

Nota:
- Actualmente el instalador se publica tanto en la raíz como en la carpeta versionada (duplica espacio, pero simplifica descargas directas y rollback).
- `latest.json` apunta al instalador de la raíz del canal.

### Política pública mínima del bucket (solo releases)
El backend de DupliManager consulta `latest.json` desde el servidor Windows, por lo que el objeto debe ser legible.

Ejemplo de policy (ajusta bucket/prefijo):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadDupliManagerReleases",
      "Effect": "Allow",
      "Principal": "*",
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::duplimanager/duplimanager/client/*"]
    }
  ]
}
```

## Comprobación de updates en la app (`latest.json`)
DupliManager incluye una comprobación de actualizaciones al abrir el panel:
- consulta una URL `latest.json`
- compara con la versión runtime
- muestra aviso en footer si hay una versión nueva

Endpoint de diagnóstico:
- `GET /api/system/update-check`

## Scripts de release (local vs GitHub)
### `scripts/release.ps1` (interactivo, recomendado)
Unifica el flujo y te pregunta lo mínimo (versión, tipo de release).

Ejemplo:
```powershell
.\scripts\release.ps1
```

Puede lanzar:
- `release-local.ps1` (si eliges `local`)
- `release-github.ps1` (si eliges `github`)

### `scripts/release-local.ps1` (preparar release en tu PC)
Uso:
- Validar antes de publicar
- Generar instalador local
- Generar `SHA256SUMS.txt`
- Generar `release-notes.md` desde commits (desde el último tag)
- (Opcional) actualizar `CHANGELOG.md`
- Sincronizar `server_py/version.py` con la versión que se va a empaquetar

Ejemplo:
```powershell
.\scripts\release-local.ps1 -Version 1.0.2 -Mode client -UpdateChangelog
```

Salida (local):
- `installer/output/DupliManager-client-setup-1.0.2.exe`
- `installer/output/SHA256SUMS.txt`
- `installer/output/release-notes.md`
- `installer/output/release-metadata.local.json`

### `scripts/release-github.ps1` (publicar versión en GitHub)
Uso:
- Empujar `main`
- Crear tag `vX.Y.Z`
- Empujar el tag para disparar el workflow de GitHub Actions
- Sincronizar y commitear `server_py/version.py` automáticamente si no coincide con la versión del release

Ejemplo (publicación normal):
```powershell
.\scripts\release-github.ps1 -Version 1.0.2
```

Ejemplo (preparar release local primero y luego publicar):
```powershell
.\scripts\release-github.ps1 -Version 1.0.2 -RunLocalRelease
```

Notas:
- `release-github.ps1` por defecto exige árbol limpio (`git status` limpio).
- Si usas `-RunLocalRelease -UpdateChangelog`, el script te pedirá implícitamente que hagas commit del `CHANGELOG.md` antes de crear el tag (para no etiquetar una versión con cambios sin commitear).

## Cuándo usar cada uno
- **`release.ps1` (interactivo)**: uso diario recomendado si no quieres recordar comandos/parámetros.
- **Release local**: cuando quieres validar el instalador, calcular hash y revisar notas antes de publicar.
- **Release GitHub**: cuando ya estás listo para publicar y quieres que GitHub Actions compile/publice automáticamente.

### Artefactos publicados
- `DupliManager-client-setup-x.y.z.exe`
- `SHA256SUMS.txt`
- `release-metadata.json`
- `release-notes.md`
- `latest.json` (canal de updates, publicado en Wasabi para cliente)

## Diferencia cliente vs soporte (importante)
- **Cliente**
  - Ejecuta el panel/API (`server_py/main.py`)
  - Incluye `web/`
  - Excluye `server_py.tools.maintenance`
  - Excluye `tkinter` para evitar dependencias gráficas en servidor
- **Soporte**
  - Solo CLI de mantenimiento (`server_py/tools/maintenance.py`)
  - No requiere UI web
  - Herramienta interna, no empaquetar junto al instalador del cliente

## Checklist de pre-release (Windows)
1. `git status` limpio (sin logs ni artefactos temporales).
2. Ejecutar pruebas MVP:
   ```powershell
   .\.venv\Scripts\python.exe -m unittest discover -s tests -v
   ```
3. Validar sintaxis backend/frontend (si hubo cambios Python/JS).
4. Generar build cliente.
5. Arrancar build cliente en una VM Windows limpia:
   - abre panel
   - confirma que el servicio `DupliManager` está creado y en ejecución
   - login panel
   - backup manual
   - restore manual
   - migración de secretos (`Configuración`)
6. Confirmar que `pick-folder` en build empaquetada responde con mensaje controlado (no traceback).
7. Confirmar que el CLI de mantenimiento **no** está en la distribución de cliente.
8. Confirmar en el panel (`Configuración -> Rutas del sistema`) que:
   - `mode = empaquetado`
   - `dataDir/configDir/logsDir` apuntan a la instalación (`ProgramData`)
   - `webDir` apunta al bundle (`_internal`)

## Checklist de empaquetado/instalador (fase siguiente)
1. Definir usuario de servicio y permisos (LocalSystem vs cuenta dedicada).
2. Abrir firewall solo si aplica (por defecto `127.0.0.1`).
3. Procedimiento de upgrade y rollback.
4. Estrategia de auto-updater (si aplica) o canal de upgrades manuales firmados.
5. Healthcheck post-instalación automatizado (comprobar `/api/health`).

## Notas operativas
- La build cliente usa `web/`, `docs.html` y la carpeta `docs/` (incluyendo `docs/user-manual.md`) como datos incluidos.
- La build cliente incluye `web/index.html`, `web/css/` y `web/js/` de forma explícita (evita arrastrar carpetas ocultas no deseadas como `web/.duplicacy`).
- Si `bin\duplicacy.exe` no existe, el script de build avisa y sigue.
- En runtime (Windows), DupliManager intentará **descargar automáticamente** `duplicacy.exe` desde GitHub Releases al primer uso (backup/restore/listados remotos) si no encuentra el binario configurado.
- Requisito para auto-descarga runtime: salida HTTPS a `github.com` / `api.github.com`.
- La UI muestra la versión runtime desde `server_py/version.py`; los scripts de release sincronizan este archivo para evitar descuadres entre la versión instalada y el tag publicado.
- La eliminación del archivo `server.log` del repo forma parte de la higiene pre-build (artefacto de runtime).
