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
   - login panel
   - backup manual
   - restore manual
   - migración de secretos (`Configuración`)
6. Confirmar que `pick-folder` en build empaquetada responde con mensaje controlado (no traceback).
7. Confirmar que el CLI de mantenimiento **no** está en la distribución de cliente.

## Checklist de empaquetado/instalador (fase siguiente)
1. Crear instalador MSI/EXE (Inno Setup/WiX o equivalente).
2. Instalar como servicio Windows (1 proceso).
3. Definir usuario de servicio y permisos.
4. Abrir firewall solo si aplica (por defecto `127.0.0.1`).
5. Procedimiento de upgrade y rollback.

## Notas operativas
- La build cliente usa `web/` y `docs.html` como datos incluidos.
- Si `bin\duplicacy.exe` no existe, el script avisa y sigue; la instalación deberá resolver ese binario por otro medio.
- La eliminación del archivo `server.log` del repo forma parte de la higiene pre-build (artefacto de runtime).

