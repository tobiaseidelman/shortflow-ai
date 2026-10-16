# Clips

Clips es una sección separada de Fondos y de las historias narradas. Recibe un
MP4 con audio original y propone fragmentos para revisar y exportar. No publica
ningún archivo en redes sociales.

1. Abrí **Clips**, elegí el MP4, la cantidad máxima de propuestas (1, 3 o 6) y
   su duración máxima (30–120 segundos). El límite inicial es 1 GB / 30 minutos.
2. Pulsá **Subir y buscar clips**. Se sube por partes de 4 MB. Si falla la
   conexión, seleccioná el mismo archivo para reanudar. Los originales quedan
   guardados separados de la biblioteca de fondos.
3. La transcripción local identifica frases completas con tiempos. La IA
   propone contexto y una revelación posterior al corte. Un modelo visual
   describe imágenes del inicio y de ambos lados del corte; una revisión
   contrasta esas observaciones con la propuesta. No analiza todos los fotogramas.
4. Revisá cada resultado en el reproductor. Ajustá inicio/final con los campos
   o con **Marcar aquí**. **Agregar continuación** empieza en el final elegido
   y propone hasta 60 segundos adicionales para ajustar manualmente.
5. Guardá o exportá. Los clips no pueden solaparse. La exportación permite
   9:16 con franjas negras para preservar toda la imagen, o proporción original.
   Conserva el audio y no agrega una voz ni subtítulos nuevos.
6. Descargá cada MP4 desde su reproductor de salida. Si editás después, las
   descargas anteriores se identifican como una versión anterior.

## Instalación y recursos

Después de actualizar el repositorio, instalá `requirements.txt` en el entorno
virtual y reiniciá la aplicación. Se agrega `faster-whisper` para transcribir.
La primera ejecución descarga Whisper small y Gemma 3 4B, además del modelo
de texto existente si todavía no está descargado. Se usan secuencialmente para
reducir el consumo de memoria. El análisis puede ser lento en CPU; la pantalla
muestra la fase actual y se puede recuperar al volver a Clips.

Un reinicio interrumpe la tarea en curso, pero conserva el MP4, la transcripción
terminada, los cortes guardados y las exportaciones completadas. Se puede
reintentar sin subir el original de nuevo. Eliminar un proyecto borra sus archivos.

## Límites de las propuestas

Las transcripciones y las descripciones visuales pueden equivocarse. El modelo
puede no reconocer un resultado que ya aparece en pantalla. La IA devuelve
**propuestas**, no una garantía de suspenso ni de cortes perfectos. Los tiempos
de voz son estimaciones. La vista previa y el ajuste manual son parte del flujo.
Si no hay diálogo suficiente o no se encuentra un corte con revelación posterior,
no se inventan clips: se conserva el original y se habilita la edición manual.

Validación: `pytest tests/test_clip_projects.py`, `python -m scripts.check_clips_ui`.
La prueba de interfaz usa respuestas simuladas; las pruebas de exportación usan
FFmpeg real. La calidad editorial debe comprobarse con el video del usuario.
