# ShortFlow AI — GitHub Codespaces ready

ShortFlow AI es un MVP web para analizar videos largos, crear candidatos de clips de fondo de aproximadamente 4–8 segundos, calcular Hook Score y attention curves, optimizar secuencias con anti-repetición y renderizar video vertical 9:16 con FFmpeg.

## La forma más fácil: GitHub Codespaces

No necesitás instalar Python ni FFmpeg en tu Mac.

1. Abrí este repositorio en GitHub.
2. Elegí **Code → Codespaces → Create codespace on main**.
3. Esperá a que termine la instalación de Python 3.12, FFmpeg, Ollama y las dependencias.
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
- Ollama para generar historias con IA local
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

El análisis de video, scoring, persistencia de clips, optimización de secuencias y render son locales al entorno. Las historias se generan con IA local mediante Ollama y Qwen3, sin API de pago. Cada generación escribe y guarda dos partes conectadas. El render actual produce solo el fondo: todavía no incorpora voz ni subtítulos, aunque el short pueda quedar vinculado a una historia. Servicios externos de TTS natural o importación autorizada desde plataformas requieren un proveedor/API y credenciales propias; el proyecto no incluye mecanismos para evadir DRM, autenticación ni restricciones de plataformas.

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
  story_engine.py      # Modelo local y reglas narrativas
  story_routes.py      # Generación en segundo plano y partes vinculadas
  static/              # app.css, app.js
  templates/           # index.html
storage/
  uploads/
  renders/
  temp/
tests/
scripts/               # Comprobación opcional con el modelo real
.env.example
.gitignore
pytest.ini
requirements.txt
requirements-dev.txt
start.sh
```

`start.sh` selecciona `.venv/bin/python` y cambia a la raíz del proyecto, por lo que también funciona invocándolo por ruta desde otra carpeta. Verifica Python y FFmpeg antes de arrancar.

Las rutas predeterminadas de SQLite, plantillas, recursos estáticos y almacenamiento se calculan desde el código de la aplicación. Para cambiarlas, exportá `SHORTFLOW_DB_PATH` o `SHORTFLOW_STORAGE_DIR`; también podés exportar `HOST` y `PORT`. `.env.example` documenta las opciones: no se carga automáticamente. Las pruebas usan almacenamiento temporal y no modifican tus videos ni tu base de datos.

## Historias tipo Reddit: parte 1 y parte 2

En **Historias**, escribí una idea y elegí la duración **de cada parte**. El botón **GENERAR PARTE 1 Y 2** produce una misma historia de ficción en primera persona: conflicto y suspenso en la primera parte; continuación y resolución en la segunda. El modelo primero prepara un plan común: agravio, recurso del protagonista, enfrentamiento pendiente y decisión final. Después escribe ambas partes en una misma solicitud para compartir personajes y hechos. La duración elegible es de 30, 45, 60, 90 o 120 segundos por parte; 90 es el valor inicial. No son publicaciones extraídas de Reddit.

El motor usa [Qwen2.5 7B](https://ollama.com/library/qwen2.5:7b) mediante [Ollama local](https://docs.ollama.com/faq). No requiere claves, saldo ni una API de pago. La descarga inicial ocupa aproximadamente **4,7 GB**, además del programa Ollama. Se guarda en `storage/ollama/models/`, fuera de Git. En Codespaces consume la cuota de cómputo y almacenamiento del entorno; no significa que Codespaces sea ilimitado o gratuito.

- **Codespace existente:** guardá tu trabajo, actualizá la rama con `git pull --ff-only` y ejecutá **Codespaces: Rebuild Container**. Luego `bash start.sh`.
- **Codespace nuevo:** Ollama se instala con el contenedor. La primera generación descarga el modelo y muestra su progreso; las siguientes reutilizan esa descarga.
- **Fuera de Codespaces:** instalá [Ollama](https://ollama.com/download) en la misma máquina donde se ejecuta ShortFlow. La aplicación utiliza únicamente `127.0.0.1:11434`. No hace falta publicar ese puerto.
- Prevé varios minutos de generación en CPU y suficiente memoria libre para un modelo de 7B; el tiempo depende del equipo. Evitá renderizar video mientras genera historias si falta memoria. El modelo se descarga de memoria al terminar.

La pantalla muestra progreso y puede recuperarlo al volver a **Historias**. Solo se permite una generación a la vez. Reiniciar el servidor interrumpe el trabajo activo y muestra un mensaje para reintentarlo; las historias ya guardadas se conservan. El despliegue actual usa un único proceso de Uvicorn, como `start.sh`.

Las dos partes se guardan en una transacción, vinculadas por una tabla nueva, sin modificar las historias anteriores. Cada parte aparece por separado en **Crear Short**. **Elegir una historia aún no añade voz ni subtítulos al render**: esa integración está pendiente.

Se comprueban extensión aproximada, frases completas y ausencia de frases largas idénticas; si falla el formato, se permite una reescritura. Estas comprobaciones no garantizan por sí solas calidad narrativa ni coherencia: revisá ambos textos antes de usarlos. La duración es una estimación basada en palabras.

Las pruebas habituales simulan el modelo y no descargan pesos. Para probar generación real:

```bash
.venv/bin/python -m scripts.check_story_model
```

Ese comando descarga el modelo en una carpeta temporal y muestra una historia de ejemplo. En GitHub Actions se ejecuta únicamente al lanzar el workflow manualmente o con un commit que incluya `[model-smoke]`.
