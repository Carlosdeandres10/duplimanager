# DupliManager

Aplicación web de gestión de copias de seguridad basada en el binario CLI de Duplicacy, con backend en Python (FastAPI) y frontend premium en vanilla JS.

## MVP Walkthrough

### Qué se construyó

Una aplicación completa de gestión de backups que corre en `http://localhost:8500`.

### Arquitectura

```text
repositorio duplicacy/
├── bin/                          # duplicacy.exe (v3.2.5)
├── config/                       # JSON de configuración auto-generado
├── logs/                         # Logs con rotación diaria
├── server_py/
│   ├── main.py                   # Servidor FastAPI (puerto 8500)
│   ├── services/
│   │   └── duplicacy.py          # Wrapper Python del CLI
│   └── utils/
│       ├── config_store.py       # Gestión de configuración
│       └── logger.py             # Logging con rotación diaria
├── web/
│   ├── index.html                # SPA con 6 vistas
│   ├── css/styles.css            # Diseño premium dark mode
│   └── js/
│       ├── api.js                # Cliente REST API
│       └── app.js                # Router SPA + lógica de vistas
├── requirements.txt              # Dependencias Python
└── package.json                  # Scripts para arrancar la app
```

### Features implementadas

- `Dashboard`: tarjetas de estado, repositorios y acción "New Repo"
- `New Repository`: wizard modal (nombre, ruta, snapshot ID, storage URL, password)
- `Backup`: ejecución por repositorio con progreso en tiempo real vía SSE y log en vivo
- `Snapshots`: listado de revisiones en tabla ordenable
- `Restore`: selección de repo + revisión y restauración con overwrite
- `Settings`: ruta del binario Duplicacy, puerto del servidor, idioma
- `Logs`: listado de logs diarios y visualización inline
- `Toast notifications`: feedback de éxito/error/aviso en todas las operaciones

### Verificaciones (MVP)

- `GET /api/health` -> `{"ok": true, "version": "1.0.0"}`
- `GET /api/repos` -> `{"ok": true, "repos": []}`
- `GET /` (frontend) -> `200 OK` (título: `DupliManager — Copias de Seguridad Inteligentes`)
- Inicio del servidor -> `http://localhost:8500`

## Quick Start

1. Descarga `duplicacy.exe` desde [duplicacy.com](https://duplicacy.com) (Windows AMD64).
2. Colócalo en `bin/duplicacy.exe`.
3. Instala dependencias Python: `pip install -r requirements.txt`.
4. Arranca la app: `npm start`.
5. Abre `http://localhost:8500`.
6. Crea tu primer repositorio desde el dashboard.

## Troubleshooting

- `duplicacy.exe` no se encuentra:
  verifica que existe `bin/duplicacy.exe` y revisa la ruta configurada en `Settings`.
- `python` no se reconoce al ejecutar `npm start` (Windows):
  usa `py -m server_py.main` directamente o añade Python al `PATH`.
- Puerto `8500` ocupado:
  cierra el proceso que lo usa o cambia el puerto desde `Settings` (si ya tienes la app iniciada en otro puerto).
- Error al importar FastAPI/Uvicorn:
  ejecuta `pip install -r requirements.txt` en el mismo entorno/venv con el que arrancas la app.
- Problemas de permisos al hacer backup/restore:
  evita rutas protegidas o ejecuta la terminal con permisos elevados cuando sea necesario.
