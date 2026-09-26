# ShortFlow AI — GitHub Codespaces ready

ShortFlow AI es un MVP web para analizar videos largos, crear candidatos de clips de fondo de aproximadamente 4–8 segundos, calcular Hook Score y attention curves, optimizar secuencias con anti-repetición y renderizar video vertical 9:16 con FFmpeg.

## La forma más fácil: GitHub Codespaces

No necesitás instalar Python ni FFmpeg en tu Mac.

1. Creá un repositorio nuevo en GitHub.
2. Subí **todo el contenido de esta carpeta** al repositorio, incluyendo `.devcontainer` y `.github`.
3. En GitHub abrí **Code → Codespaces → Create codespace on main**.
4. Esperá a que termine la creación. Codespaces instala automáticamente Python 3.12, FFmpeg y las dependencias.
5. ShortFlow AI se inicia automáticamente en el puerto `8000`. Cuando aparezca la notificación del puerto, elegí **Open in Browser**.

Si el navegador no se abre solo, en Codespaces abrí la pestaña **Ports** y hacé clic en el enlace correspondiente al puerto `8000`.

### Reiniciar la aplicación

En la terminal del Codespace:

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
- Inicio automático del servidor al iniciar el Codespace

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

Requiere Python 3.10+ y FFmpeg disponible en PATH.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash start.sh
```

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest -q
```

También se incluye un workflow de GitHub Actions en `.github/workflows/ci.yml` que prueba el proyecto con Python 3.12 y FFmpeg después de cada push o pull request.

## Alcance actual

El análisis de video, scoring, persistencia de clips, optimización de secuencias y render son locales al entorno. La generación de historias actual funciona sin API externa mediante plantillas. Servicios externos de TTS natural o importación autorizada desde plataformas requieren un proveedor/API y credenciales propias; el proyecto no incluye mecanismos para evadir DRM, autenticación ni restricciones de plataformas.
