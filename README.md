# ShortFlow AI — GitHub Codespaces ready

ShortFlow AI es un MVP web para analizar videos largos, crear candidatos de clips de fondo de aproximadamente 4–8 segundos, calcular Hook Score y attention curves, optimizar secuencias con anti-repetición y renderizar video vertical 9:16 con FFmpeg.

## La forma más fácil: GitHub Codespaces

No necesitás instalar Python ni FFmpeg en tu Mac.

1. Abrí este repositorio en GitHub.
2. Elegí **Code → Codespaces → Create codespace on main**.
3. Esperá a que termine la instalación de Python 3.12, FFmpeg y las dependencias.
4. En la terminal ejecutá `bash start.sh`.
5. Cuando aparezca la notificación del puerto `8000`, elegí **Open in Browser**.

Si ya tenías un Codespace anterior, ejecutá **Codespaces: Rebuild Container** desde la paleta de comandos para aplicar esta configuración.

Si el navegador no se abre solo, en Codespaces abrí la pestaña **Ports** y hacé clic en el enlace correspondiente al puerto `8000`.

### Iniciar o reiniciar la aplicación

En la terminal del Codespace (para reiniciar, primero detené el servidor con `Ctrl+C`):

```bash
bash start.sh
```

### Verificar que está funcionando

```bash
curl http://127.0.0.1:8000/api/health
```

Deberías ver un JSON que indica si FFmpeg está disponible y si el almacenamiento es escribible.

## Qué configura Codespaces automáticamente

- Python 3.12
- FFmpeg
- FastAPI + Uvicorn
- OpenCV headless
- SQLite
- Puerto 8000 reenviado al navegador
- Dependencias instaladas en `.venv/`; inicio manual con `bash start.sh`

## Datos y archivos

La base SQLite y los videos subidos/renderizados **no se guardan en Git**. `.gitignore` excluye:

- `shortflow.db`
- `storage/uploads/*`
- `storage/renders/*`
- `storage/temp/*`
- `.venv/`
- archivos temporales y secretos

Dentro de un Codespace, esos datos permanecen en el espacio de trabajo mientras conserves ese Codespace, pero GitHub Codespaces no debe considerarse almacenamiento permanente de producción.

## Ejecutar fuera de Codespaces

Requiere Python 3.12+ y FFmpeg disponible en PATH.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash start.sh
```

## Pruebas

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

También se incluye un workflow de GitHub Actions en `.github/workflows/ci.yml` que prueba el proyecto con Python 3.12 y FFmpeg después de cada push o pull request.

## Alcance actual

El análisis de video, scoring, persistencia de clips, optimización de secuencias y render son locales al entorno. La generación de historias actual funciona sin API externa mediante plantillas. Servicios externos de TTS natural o importación autorizada desde plataformas requieren un proveedor/API y credenciales propias; el proyecto no incluye mecanismos para evadir DRM, autenticación ni restricciones de plataformas.

## Estructura

```text
.devcontainer/          # Python 3.12, FFmpeg y configuración de Codespaces
.github/workflows/     # Pruebas automáticas
app/
  __init__.py
  main.py              # FastAPI y rutas
  db.py                # SQLite
  models.py
  video_engine.py
  static/              # app.css, app.js
  templates/           # index.html
storage/
  uploads/
  renders/
  temp/
tests/
.env.example
.gitignore
pytest.ini
requirements.txt
requirements-dev.txt
start.sh
```

`start.sh` selecciona `.venv/bin/python` y cambia a la raíz del proyecto, por lo que también funciona invocándolo por ruta desde otra carpeta. Verifica Python y FFmpeg antes de arrancar.

Las rutas predeterminadas de SQLite, plantillas, recursos estáticos y almacenamiento se calculan desde el código de la aplicación. Para cambiarlas, exportá `SHORTFLOW_DB_PATH` o `SHORTFLOW_STORAGE_DIR`; también podés exportar `HOST` y `PORT`. `.env.example` documenta las opciones: no se carga automáticamente. Las pruebas usan almacenamiento temporal y no modifican tus videos ni tu base de datos.
