# DupliManager

DupliManager es una interfaz web intuitiva (Panel de Control) para administrar copias de seguridad usando **Duplicacy**, motor de respaldos reconocido por su velocidad y eficiencia en deduplicación.

Esta herramienta está pensada para **Administradores de Sistemas**, facilitando la configuración visual, el monitoreo y la restauración de datos sin tener que pelearse constantemente con la línea de comandos de Duplicacy.

---

## 🏗️ Cómo funciona la Arquitectura (Vista de Sistemas)

El sistema se compone de tres piezas fundamentales que se comunican entre sí:

1. **El Motor Core (`bin/duplicacy.exe`)**: Es el ejecutable oficial de Duplicacy que hace el trabajo duro de cifrar, subir y descargar archivos a tu almacenamiento en la nube (ej. Wasabi, S3, B2) o discos locales.
2. **El Servidor/API en Python (`server_py/main.py`)**: Es un servicio ligero que actúa como "controlador" en el puerto `8500`. Recibe las órdenes tuyas desde la web, construye los comandos complicados para Duplicacy y captura su salida para mostrártela en tu pantalla. También gestiona las tareas programadas (el "cron" interno de los backups).
3. **El Panel Web (`web/index.html`)**: Es la web en sí (Dashboard) a la que accedes en tu navegador a través de `http://localhost:8500`.

---

## 📂 Dónde guarda DupliManager sus configuraciones

A diferencia de otros programas, DupliManager guarda todos sus ajustes y base de datos en archivos planos `.json` muy sencillos, fáciles de revisar, hacer backup o editar a mano si fuese necesario.

- **`config/settings.json`**: Aquí se guardan los "Ajustes" generales de la App (ej. en qué puerto arranca la web, la ruta de tu ejecutable de duplicacy.exe, el idioma).
- **`config/storages.json`**: El almacén de tus cuentas de destino de la nube (tus claves de acceso temporales The Wasabi Access Key, directorios S3, URLs, etc.).
- **`config/repos.json`**: El registro de tus "Tareas de Backup" programadas (qué carpetas locales estás copiando, hacia qué Storage de destino, la contraseña de cifrado, la frecuencia del cronjob, etc.).
- **`logs/`**: Todos los registros crudos del servidor, los fallos y las trazas. El archivo principal es `duplimanager.log`. Esta carpeta rota los logs diariamente para no cometer tu disco duro.

---

## 🚀 Instalación y Puesta en Marcha Rápida

1. **Bájate el Motor**: Descarga `duplicacy.exe` de [duplicacy.com](https://duplicacy.com) (Windows AMD64). Mételo dentro de la carpeta `bin/` del proyecto.
2. **Prepara el entorno de Python**: Abre una terminal en la carpeta del proyecto y ejecuta: `pip install -r requirements.txt`. Esto instalará las librerías necesarias para el servidor web.
3. **Arranca el Servidor**: Puedes utilizar el script `npm start` si tienes Node, o ejecutar directamente el backend con python `py -m server_py.main` o `python -m server_py.main`.
4. **Accede al Panel**: Abre tu navegador y dirígete a `http://localhost:8500`.

---

## ✅ Contratos y Tests MVP (mantenimiento con IA)

Para reducir regresiones en cambios funcionales:

- **Contratos (reglas cortas)**:
  - `docs/notifications-contract.md`
  - `docs/backups-contract.md`
  - `docs/restore-contract.md`
- **Guía de pruebas MVP**:
  - `docs/testing-mvp.md`
- **Comando de pruebas**:
  - `python -m unittest discover -s tests -v`

---

## 🏗️ Qué hace cada archivo y carpeta (Arquitectura Técnica)

### 1. El Servidor Backend (`server_py/`)

El corazón lógico. Funciona en segundo plano sin importar si tienes la pestaña de tu navegador abierta o no.

- **`main.py`**: El archivo que arranca el puerto `8500` e inicia Uvicorn (el servidor de red).
- **Las Rutas (`routers/`)**: Son los semáforos. `backups.py` maneja las peticiones para arrancar o parar copias. `restore.py` escanea la nube para descargar tu árbol de ficheros.
- **Los Motores (`core/`)**: Funcionan en las sombras. En concreto, `helpers.py` actúa como un _Cron Job_ perpetuo: despierta cada ciertos segundos, lee a qué hora tocan los próximos backups según `repos.json` y los dispara automáticamente.
- **El Enlace (`services/duplicacy.py`)**: Este es el único archivo que de verdad interactúa físicamente con el programa `duplicacy.exe`. Le pasa las contraseñas, recoge la barra de progreso y te la envía a la pantalla.

### 2. El Panel Web Front-end (`web/js/`)

El cerebro de la página web que ves en tu navegador. Diseñado de forma separada (Módulos) para que nunca tengas que recargar la web.

- **`api.js`**: El mensajero. Es el único fichero autorizado a hacer peticiones por red al servidor de Python. Si falla la conexión, este archivo saca el error.
- **`modules/views/`**: Cada archivo aquí (ej: `dashboard.js`, `restore.js`, `logs.js`) es responsable de dibujar una pestaña entera de la aplicación.
- **`modules/components/`**: Pequeños modales flotantes. Por ejemplo, `repositories_modals.js` dibuja la ventana para introducir tus credenciales de Amazon S3, y `content_selector.js` dibuja el explorador visual de tus discos duros locales.

---

## 🚑 Troubleshooting (Solución de problemas comunes)

### ¿El servidor no arranca y dice "puerto 8500 en uso"?

Normalmente es porque Windows ha dejado un proceso fantasma de Python ejecutándose en segundo plano (un reinicio fallido, por ejemplo).  
**Solución rápida en PowerShell:** `Stop-Process -Name python -Force` y luego vuelve a arrancar el servidor.

### ¿DupliManager funciona pero pone "Executable not found"?

Ve al menú **Settings (Configuración)** en la web inferior izquierda y asegúrate de que la ruta hacia el archivo ejecutable (`bin/duplicacy.exe`) es correcta y el archivo realmente está allí en la carpeta.

### ¿Se ha colgado una copia de seguridad o no avanza?

Puedes ver los `Logs` en tiempo real desde la web o entrar a la carpeta `/logs` de Windows y leer los ficheros de texto. También puedes matar el proceso completo si se ha bloqueado debido a problemas de red.

### ¿He borrado un Repositorio pero sigue apareciendo la carpeta `.duplicacy/` original en mi disco duro?

DupliManager elimina la vinculación **lógica** de su interfaz web (borra sus cronogramas y accesos directos), pero para extremar la seguridad contra la pérdida de datos, **jamás** borra configuraciones ni carpetas de los archivos reales que hay en tu disco duro si fueron creados originalmente desde tu sistema sin permisos. Si quisieras limpiarlo todo por tu cuenta, solo deberías borrar la carpeta `.duplicacy` escondida que queda residual en el origen local.
