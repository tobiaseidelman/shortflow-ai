# ShortFlow AI — GitHub Codespaces ready

ShortFlow AI crea dos videos verticales de una misma historia: parte 1 con suspenso y parte 2 con desenlace. Permite importar fondos, generar y editar relatos, agregar voz en español y subtítulos, y descargar ambos MP4. La generación de texto y voz se ejecuta dentro del entorno, sin una API de pago.

## La forma más fácil: GitHub Codespaces

No necesitás instalar Python ni FFmpeg en tu Mac.

1. Abrí este repositorio en GitHub.
2. Elegí **Code → Codespaces → Create codespace on main**.
3. Esperá a que termine la instalación de Python 3.12, FFmpeg, Ollama y las dependencias.
4. En la terminal ejecutá `bash start.sh`.
5. Cuando aparezca la notificación del puerto `8000`, elegí **Open in Browser**.

Si ya tenías un Codespace anterior, detené el servidor con `Ctrl+C`, guardá tus cambios y ejecutá `git pull --ff-only`. Después abrí la paleta con `F1`, elegí **Codespaces: Rebuild Container**, esperá la instalación y ejecutá `bash start.sh`. Recargá la página de la aplicación para cargar los nuevos botones.

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

El análisis de video, scoring, persistencia de clips, optimización de secuencias y render son locales al entorno. Las historias se generan con IA local mediante Ollama y Qwen2.5, sin API de pago. Cada generación escribe y guarda dos partes conectadas. El render de historias incorpora voz local Piper y subtítulos sobre un fondo vertical. También se puede generar un fondo sin historia. La importación pública de YouTube usa yt-dlp y Node 22, sin claves. El proyecto no incluye mecanismos para evadir DRM, autenticación ni restricciones de plataformas.

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

El generador crea borradores originales: revisá personajes, coherencia y desenlace antes de publicar. Los textos se pueden editar y guardar dentro de ShortFlow.

En **Historias**, escribí una idea y elegí la duración **de cada parte**. El botón **GENERAR PARTE 1 Y 2** produce una misma historia de ficción en primera persona: conflicto y suspenso en la primera parte; continuación y resolución en la segunda. El modelo primero prepara un plan común: agravio, recurso del protagonista, enfrentamiento pendiente y decisión final. Después escribe cada parte como prosa en una solicitud separada: la segunda recibe el plan y el texto exacto de la primera. Cada parte tiene una revisión de extensión, frase final y señales de primera persona; si falla, el modelo recibe el borrador para corregirlo una vez. La duración elegible es de 30, 45, 60, 90 o 120 segundos por parte; 90 es el valor inicial. No son publicaciones extraídas de Reddit.

El motor usa [Qwen2.5 7B](https://ollama.com/library/qwen2.5:7b) mediante [Ollama local](https://docs.ollama.com/faq). No requiere claves, saldo ni una API de pago. La descarga inicial ocupa aproximadamente **4,7 GB**, además del programa Ollama. Se guarda en `storage/ollama/models/`, fuera de Git. En Codespaces consume la cuota de cómputo y almacenamiento del entorno; no significa que Codespaces sea ilimitado o gratuito.

- **Codespace existente:** guardá tu trabajo, actualizá la rama con `git pull --ff-only` y ejecutá **Codespaces: Rebuild Container**. Luego `bash start.sh`.
- **Codespace nuevo:** Ollama se instala con el contenedor. La primera generación descarga el modelo y muestra su progreso; las siguientes reutilizan esa descarga.
- **Fuera de Codespaces:** instalá [Ollama](https://ollama.com/download) en la misma máquina donde se ejecuta ShortFlow. La aplicación utiliza únicamente `127.0.0.1:11434`. No hace falta publicar ese puerto.
- Prevé varios minutos de generación en CPU y suficiente memoria libre para un modelo de 7B; el tiempo depende del equipo. La aplicación impide iniciar un render narrado y una generación de historias al mismo tiempo. El modelo se descarga de memoria al terminar.

La pantalla muestra progreso y puede recuperarlo al volver a **Historias**. Solo se permite una generación a la vez. Reiniciar el servidor interrumpe el trabajo activo y muestra un mensaje para reintentarlo; las historias ya guardadas se conservan. El despliegue actual usa un único proceso de Uvicorn, como `start.sh`.

Las dos partes se guardan en una transacción, vinculadas por una tabla nueva, sin modificar las historias anteriores. Cada parte aparece por separado en **Crear Short**. Elegir una historia crea un video con voz y subtítulos. El botón **CREAR LOS DOS VIDEOS** genera ambos episodios y muestra dos enlaces de descarga.

Se comprueban extensión aproximada, frases completas y ausencia de frases largas idénticas; si falla el formato, se permite una reescritura. Estas comprobaciones no garantizan por sí solas calidad narrativa ni coherencia: revisá ambos textos antes de usarlos. La duración es una estimación basada en palabras.

Las pruebas habituales simulan el modelo y no descargan pesos. Para probar generación real:

```bash
.venv/bin/python -m scripts.check_story_model
```

Ese comando descarga el modelo en una carpeta temporal y muestra una historia de ejemplo. En GitHub Actions se ejecuta únicamente al lanzar el workflow manualmente o con un commit que incluya `[model-smoke]`.


## Importar fondos de YouTube

En **Fondos**, pegá un enlace de un video público individual de YouTube, confirmá tu autorización para reutilizarlo y pulsá **IMPORTAR VIDEO**. ShortFlow descarga los **primeros 10 minutos**, hasta 720p, y analiza automáticamente los clips antes de mostrarlo en la biblioteca. Podés volver a Fondos para recuperar el progreso. Para elegir otro fragmento, subí un archivo recortado.

Se aceptan videos de hasta dos horas; el archivo importado tiene un límite de 1 GB. No se admiten listas completas ni transmisiones en vivo. La descarga tiene un tiempo máximo de 20 minutos y solo se admite una importación a la vez. Los archivos temporales se eliminan al terminar o fallar. Los datos anteriores se conservan.

El contenedor instala Node 22 y `requirements.txt` incluye `yt-dlp[default]`. Fuera de Codespaces, necesitás Node 22 o superior y FFmpeg en PATH. No se usan cookies ni credenciales: si YouTube exige iniciar sesión, bloquea la conexión o restringe un video, se muestra el motivo y sigue disponible la subida manual. Actualizar yt-dlp puede ser necesario si YouTube cambia.


## Narración, subtítulos y dos videos

1. Importá o subí un fondo.
2. Generá una historia, revisá y editá ambas partes; **GUARDAR CAMBIOS** conserva las correcciones.
3. Pulsá **CREAR LOS DOS VIDEOS**. Cada parte se guarda como un MP4 vertical de 1080×1920 con audio AAC y subtítulos incrustados.
4. Podés salir de la pantalla y volver a **Crear Short** para recuperar el progreso y los enlaces. Los videos terminados quedan en Historial.

La voz [Piper](https://github.com/OHF-Voice/piper1-gpl) `es_MX-ald-medium` se descarga una sola vez en `storage/voices`. No envía el texto a un servicio remoto. El modelo usa un conjunto de datos bajo [Unlicense](https://huggingface.co/rhasspy/piper-voices/blob/main/es/es_MX/ald/medium/MODEL_CARD); Piper usa GPL-3.0. La voz y sus licencias quedan junto al modelo. Necesita conexión para la primera descarga.

La duración final sigue el audio, no recorta la narración al tiempo estimado. Los subtítulos se alinean por frase; los grupos de hasta tres palabras usan tiempos estimados dentro de la frase. **Regenerar fondo** conserva el audio y los subtítulos originales aunque hayas editado después la historia. Para aplicar cambios de texto, generá un video nuevo.

Hay una tarea pesada de historias o videos activa a la vez para evitar agotar la memoria. Si se reinicia el servidor, el trabajo interrumpido se marca como fallido y puede reintentarse. Si solo llegó a terminar la primera parte, su descarga sigue disponible. Los renders usan carpetas temporales separadas y los fondos se repiten cuando no alcanzan para cubrir toda la voz.


### Archivos grandes desde el navegador

La subida de fondos envía bloques de 4 MB y muestra el porcentaje recibido, hasta 1 GB por archivo. El análisis empieza en segundo plano después de recibir el archivo completo; al volver a Fondos se recupera su estado. Si se corta la conexión durante el envío, seleccioná el mismo archivo en el mismo navegador y volvé a pulsar SUBIR Y ANALIZAR para reanudar. Podés cancelar una subida pendiente para elegir otro archivo. Las subidas sin terminar vencen a las 24 horas y se limpian al reiniciar o al iniciar otra subida. No se publica ningún video en GitHub.
