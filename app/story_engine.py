"""Generate connected fictional Reddit-style episodes with local Ollama only."""
import atexit
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

MODEL = 'qwen2.5:7b'
URL = 'http://127.0.0.1:11434'
LOAD_TIMEOUT = '10m'
CHAT_TIMEOUT = 1200  # Allow model loading plus generation on a CPU Codespace.
REVIEW_SCHEMA = {
    'type': 'object', 'required': ['issues'], 'additionalProperties': False,
    'properties': {'issues': {'type': 'array', 'maxItems': 4,
                              'items': {'type': 'string', 'minLength': 1}}},
}
_server = None
_http = build_opener(ProxyHandler({}))
SCHEMA = {
    'type': 'object',
    'properties': {key: {'type': 'string'} for key in ('title', 'plan', 'part1', 'part2')},
    'required': ['title', 'plan', 'part1', 'part2'],
    'additionalProperties': False,
}
SYSTEM = """Escribís ficción realista en español natural, en primera persona, para dos videos conectados.
El tema original del usuario es la fuente principal: conservá parentescos, motivos,
profesiones, quién paga y a nombre de quién está cada obligación. El plan solo completa
lo que el usuario no especificó; nunca sustituye sus hechos. No inventes nombres si
alcanza con decir mi hermano, mi madre o mi pareja.
Distinguí no querer pagar de no tener dinero, y pagar un servicio de realizar ese trabajo.
Cada giro nace de una decisión o un hecho ya presentado. No inventes dinero, objetos,
pruebas ni capacidades para resolver una escena. Respetá quién sabe cada cosa y cuándo.
Una persona excluida no aparece después dentro del evento sin una explicación.
Una sola voz cuenta TODO el relato. Preferí narración indirecta: contá qué hizo o dijo cada
persona, sin intercambiar parlamentos. Si una cita breve es indispensable, identificá ANTES
quién habla, por ejemplo «mi madre me dijo: ...». Nunca dejes una réplica sin atribución.
Contá lo que el narrador siente; los sentimientos ajenos se deducen de acciones o palabras,
no de leer la mente. Usá lenguaje oral sencillo, acciones concretas y pocos adjetivos.
Parte 1: agravio inmediato, contexto necesario, decisión y una acción que cambia la escena.
Terminá justo después de esa acción y ANTES de su respuesta o consecuencia: el corte del
video crea el suspenso. La última oración debe estar completa. No anuncies una revelación,
no ocultes información que el narrador ya contó y no uses «en la parte 2», «no vas a creer»,
«todo cambiaría» ni preguntas al público para fabricar suspenso.
Parte 2: empieza con la respuesta o consecuencia inmediata de esa MISMA acción, sin resumen,
salto atrás ni otra introducción. Luego resuelve el conflicto, sin otro final pendiente.
Cada párrafo debe aportar un hecho, una reacción o una decisión nueva. No repitas la misma acusación con otras palabras ni llenes espacio describiendo miradas, brazos cruzados o tensión.
No fuerces perdones ni venganzas espectaculares. Revisá concordancia y tiempos verbales.
Entregá solamente la prosa del episodio solicitado."""


class StoryGenerationError(Exception):
    """A safe, user-facing generation failure."""


def _request(path, payload=None, timeout=10):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(URL + path, data=data, headers={'Content-Type': 'application/json'})
    return _http.open(request, timeout=timeout)


def stop_server():
    global _server
    if _server is not None and _server.poll() is None:
        _server.terminate()
        try:
            _server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _server.kill()
            _server.wait()
    _server = None


atexit.register(stop_server)


def ensure_model(storage, progress):
    global _server
    progress('Preparando la IA local…')
    try:
        with _request('/api/tags') as response:
            models = json.load(response).get('models', [])
    except (OSError, URLError, ValueError):
        executable = shutil.which('ollama')
        if not executable:
            raise StoryGenerationError(
                'Falta instalar la IA local. En Codespaces, actualizá el proyecto y ejecutá '
                '«Codespaces: Rebuild Container». Después iniciá con bash start.sh.')
        data = Path(storage) / 'ollama'
        data.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, OLLAMA_HOST='127.0.0.1:11434',
                   OLLAMA_MODELS=str(data / 'models'), OLLAMA_NO_CLOUD='1',
                   OLLAMA_NUM_PARALLEL='1', OLLAMA_MAX_LOADED_MODELS='1',
                   OLLAMA_LOAD_TIMEOUT=LOAD_TIMEOUT)
        with (data / 'server.log').open('ab') as log:
            _server = subprocess.Popen([executable, 'serve'], env=env,
                                       stdout=log, stderr=log)
        for _ in range(60):
            try:
                with _request('/api/tags', timeout=1) as response:
                    models = json.load(response).get('models', [])
                break
            except (OSError, URLError, ValueError):
                if _server.poll() is not None:
                    raise StoryGenerationError('La IA local no pudo iniciarse. Revisá storage/ollama/server.log.')
                time.sleep(0.5)
        else:
            stop_server()
            raise StoryGenerationError('La IA local no respondió al iniciar. Volvé a intentarlo.')
    if any(model.get('name') == MODEL for model in models):
        return
    progress('Descargando la IA por primera vez (aprox. 4,7 GB). Puede tardar varios minutos…')
    try:
        # Stream download progress rather than holding the browser request open.
        with _request('/api/pull', {'model': MODEL, 'stream': True}, timeout=600) as response:
            last = None
            completed = False
            for line in response:
                item = json.loads(line)
                if item.get('error'):
                    raise StoryGenerationError('No se pudo descargar la IA. Revisá conexión y espacio libre.')
                if item.get('status') == 'success':
                    completed = True
                if item.get('total'):
                    percent = min(100, int(item.get('completed', 0) * 100 / item['total']))
                    if percent != last:
                        progress(f'Descargando componente de la IA: {percent}%')
                        last = percent
            if not completed:
                raise StoryGenerationError('La descarga quedó incompleta. Volvé a intentarlo para reanudarla.')
    except (OSError, URLError, ValueError) as exc:
        raise StoryGenerationError('La descarga de la IA se interrumpió. Volvé a intentarlo para reanudarla.') from exc


def validate_story(data, duration):
    if not isinstance(data, dict) or any(not isinstance(data.get(k), str) for k in SCHEMA['required']):
        raise ValueError('La respuesta no contiene un plan, un título y dos partes.')
    result = {k: data[k].strip() for k in SCHEMA['required']}
    if not 3 <= len(result['title']) <= 180:
        raise ValueError('El título no tiene una longitud válida.')
    if not 20 <= len(result['plan']) <= 1800:
        raise ValueError('Falta un plan breve que conecte el conflicto, el corte y el desenlace.')
    low, high = round(duration * 1.7), round(duration * 2.9)
    for part in ('part1', 'part2'):
        text = result[part]
        words = len(text.split())
        if not low <= words <= high:
            raise ValueError(f'{part} tiene {words} palabras; debe tener entre {low} y {high}.')
        if text.rstrip('”"\'»')[-1:] not in '.!?…':
            raise ValueError(f'{part} termina con una frase cortada.')
    sentences = [re.sub(r'\W+', ' ', s).strip().lower()
                 for s in re.split(r'[.!?]+', result['part1'] + ' ' + result['part2'])]
    long_sentences = [s for s in sentences if len(s.split()) >= 8]
    if len(set(long_sentences)) != len(long_sentences) or result['part1'] == result['part2']:
        raise ValueError('Las partes contienen frases repetidas.')
    return result


def complete(messages, json_mode=False):
    """Keep dialogue roles and unstructured narrative separate from the plot outline."""
    payload = {
        'model': MODEL, 'messages': messages, 'stream': False, 'keep_alive': '5m',
        # Explicit mmap avoids Ollama's CPU default of loading without mapping.
        # This profile successfully loaded Qwen on the user's 8 GiB Codespace.
        'options': {'temperature': 0.65, 'use_mmap': True, 'num_ctx': 4096,
                    'num_batch': 128, 'num_predict': 1800,
                    'seed': secrets.randbelow(2**31)},
    }
    if json_mode:
        payload['format'] = json_mode if isinstance(json_mode, dict) else 'json'
        payload['options']['temperature'] = 0
    try:
        with _request('/api/chat', payload, timeout=CHAT_TIMEOUT) as response:
            raw = json.load(response)
        if raw.get('error'):
            raise StoryGenerationError('La IA no pudo generar la historia. Revisá la memoria disponible.')
        if not raw.get('done') or raw.get('done_reason') == 'length':
            raise ValueError('La IA cortó la respuesta antes de terminar.')
        return raw.get('message', {}).get('content', '').strip()
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read(8192)).get('error', '')
        except (ValueError, OSError):
            detail = ''
        logging.getLogger(__name__).error('Ollama HTTP %s: %s', exc.code, str(detail)[:1000])
        if 'timed out waiting' in str(detail).lower():
            message = 'La IA agotó el tiempo de carga del modelo. El servicio debe reiniciarse para aplicar la configuración actualizada; tus historias guardadas se conservan.'
        elif any(term in str(detail).lower() for term in ('memory', 'out of memory', 'allocate', 'oom')):
            message = 'La IA no tiene suficiente memoria disponible. Detené otras tareas o usá un Codespace con más memoria; tus historias guardadas se conservan.'
        else:
            message = 'La IA local falló al ejecutar el modelo. El motivo quedó en la terminal y en storage/ollama/server.log.'
        raise StoryGenerationError(message) from exc
    except (URLError, OSError) as exc:
        raise StoryGenerationError('La IA local no terminó a tiempo o perdió la conexión. Volvé a intentarlo.') from exc


def validate_episode(text, duration):
    low, high = round(duration * 1.7), round(duration * 2.9)
    count = len(text.split())
    if not low <= count <= high:
        raise ValueError(f'Hay {count} palabras; se necesitan entre {low} y {high}.')
    if text.rstrip('”"\'»')[-1:] not in '.!?…':
        raise ValueError('La última frase está incompleta.')
    if not re.search(r'\b(yo|me|mi|mis|conmigo)\b', text, re.IGNORECASE):
        raise ValueError('El protagonista debe contar su propia experiencia en primera persona.')
    if re.search(r'(?im)^\s*(parte [12]|aquí (tienes|está)|título:|plan:)', text):
        raise ValueError('Entregá solo la narración, sin títulos ni explicaciones.')
    return text


def write_episode(messages, duration, progress):
    for attempt in range(2):
        text = complete(messages)
        try:
            return validate_episode(text, duration)
        except ValueError as exc:
            if attempt:
                raise StoryGenerationError('La parte no pasó la revisión: ' + str(exc)) from exc
            progress('Revisando la extensión y el punto de vista de esta parte…')
            count = len(text.split())
            target = round(duration * 2.3)
            if count > round(duration * 2.9):
                instruction = f'Recortá el texto a unas {target} palabras. Eliminá conversaciones repetidas y detalles secundarios; no agregues escenas. Conservá el desenlace.'
            elif count < round(duration * 1.7):
                instruction = f'Ampliá el texto a unas {target} palabras desarrollando acciones y sus consecuencias mediante narración, sin repetir hechos.'
            else:
                instruction = 'Corregí el punto de vista o la frase incompleta sin cambiar los hechos ni extender el texto.'
            # A fresh editing request prevents the model from rewriting both
            # episodes when only the second draft needs shortening.
            messages = [
                {'role': 'system', 'content':
                 'Sos editor de una narración en español. Corregí únicamente el texto recibido. '
                 'Conservá personajes, hechos, primera persona y última escena. '
                 'No agregues introducciones, episodios anteriores ni comentarios.'},
                {'role': 'assistant', 'content': text},
                {'role': 'user', 'content': f'Corregí únicamente este borrador. {exc} {instruction} Devolvé solo este episodio corregido.'},
            ]



def parse_review(raw):
    review = json.loads(raw)
    items = review.get('issues') if isinstance(review, dict) else None
    if not isinstance(items, list):
        raise ValueError('Falta la lista de observaciones.')
    issues = []
    for item in items:
        if isinstance(item, str):
            if item.strip():
                issues.append(item.strip())
        elif (isinstance(item, dict) and item and
              all(isinstance(value, str) for value in item.values()) and
              any(value.strip() for value in item.values())):
            # Some models return quoted evidence plus an explanation as an object.
            # Preserve ALL its fields as a correction request, never as approval.
            issues.append(json.dumps(item, ensure_ascii=False))
        else:
            raise ValueError('Observación con formato inválido.')
    if items and not issues:
        raise ValueError('Las observaciones están vacías; falta una decisión válida.')
    return issues


def request_review(messages, progress):
    for attempt in range(2):
        raw = complete(messages, json_mode=REVIEW_SCHEMA)
        try:
            return parse_review(raw)
        except ValueError as exc:
            logging.getLogger(__name__).warning('Invalid continuity review: %s; response=%r', exc, raw[:2000])
            if attempt:
                raise ValueError('La IA no devolvió una revisión de continuidad válida después de dos intentos.') from exc
            progress('Reintentando el formato de la revisión, sin volver a escribir la historia…')
            # Repeat the original review with its evidence, not an instruction to
            # reinterpret a malformed answer as a successful check.
            messages = [*messages, {'role': 'user', 'content':
                'La respuesta anterior no tenía el formato requerido. Volvé a revisar los textos. '
                'Respondé SOLO {"issues": []} si no hay errores, o '
                '{"issues": ["descripción concreta del error"]}. '
                'Cada observación debe ser una frase no vacía.'}]


def review_and_repair(theme, draft, duration, progress):
    """Bounded review; preserve complete drafts with warnings instead of discarding them."""
    for attempt in range(2):
        draft = validate_story(draft, duration)
        progress('Revisando personajes, hechos y continuidad entre las dos partes…')
        review_messages = [
            {'role': 'system', 'content':
             'Sos editor de continuidad. Compará los DOS textos con el TEMA ORIGINAL. '
             'Detectá solo errores concretos: parentescos o motivos cambiados, pagar confundido '
             'con trabajar, dinero u objetos sin origen, hechos que se contradicen, cronología '
             'imposible, personajes que saben algo sin enterarse, corte desconectado o desenlace '
             'ausente, parlamentos sin identificar quién habla ANTES, escenas repetidas sin avanzar o una promesa de revelación que sustituye la acción del corte. El tema tiene prioridad sobre cualquier invención. No pidas cambios '
             'por gusto ni inventes errores. Respondé JSON {"issues": []} si no hay errores. '
             'Si los hay, issues contiene hasta cuatro frases que citan el hecho incorrecto '
             'y explican qué debe corregirse. No reescribas todavía.'},
            {'role': 'user', 'content': json.dumps(
                {'tema_original': theme, 'parte1': draft['part1'], 'parte2': draft['part2']},
                ensure_ascii=False)}]
        try:
            issues = request_review(review_messages, progress)
        except (ValueError, StoryGenerationError) as exc:
            return {**draft, 'review_issues': ['No se pudo completar la revisión: ' + str(exc)]}
        if not issues:
            return draft
        if attempt:
            return {**draft, 'review_issues': issues}
        progress('Corrigiendo las contradicciones encontradas…')
        original = {key: draft[key] for key in ('part1', 'part2')}
        repaired = dict(draft)
        for key in ('part1', 'part2'):
            context = {'tema_original': theme, 'errores_a_corregir': issues,
                       'borrador_parte1': original['part1'], 'borrador_parte2': original['part2']}
            if key == 'part2':
                del context['borrador_parte1']
                context['parte1_definitiva'] = repaired['part1']
            prompt = (json.dumps(context, ensure_ascii=False) +
                      f'\nCorregí SOLO {key}. Entre {round(duration * 1.7)} y '
                      f'{round(duration * 2.9)} palabras. Conservá los hechos correctos; '
                      'no agregues otra trama. La parte 1 deja el enfrentamiento pendiente; '
                      'la parte 2 retoma la parte 1 definitiva y muestra la consecuencia. Solo prosa.')
            try:
                repaired[key] = write_episode([{'role': 'system', 'content': SYSTEM},
                                               {'role': 'user', 'content': prompt}], duration, progress)
            except (ValueError, StoryGenerationError):
                return {**draft, 'review_issues': issues + ['La corrección automática no terminó; conservamos el borrador anterior.']}
        try:
            draft = validate_story(repaired, duration)
        except ValueError:
            return {**draft, 'review_issues': issues + ['La corrección automática no pasó las comprobaciones; conservamos el borrador anterior.']}
    raise AssertionError('Unreachable review state')


def generate_story(theme, duration, storage, progress):
    ensure_model(storage, progress)
    system = {'role': 'system', 'content': SYSTEM}
    progress('Planificando el conflicto, el corte y el desenlace…')
    try:
        # Planning has its own brief instruction: a prose example can distract a
        # small model into copying objects or inventing unrelated twists.
        planner = {'role': 'system', 'content':
            'Sos guionista de relatos cotidianos. Diseñá una sola cadena de causa y efecto, '
            'con un conflicto fácil de entender. Conservá TODOS los hechos explícitos del tema: '
            'parentescos, motivos, profesiones, pagos y obligaciones. No reemplaces al hermano '
            'por su novia ni inventes un nombre para el narrador. '
            'No escribas prosa todavía. Respondé solo el JSON solicitado.'}
        outline = complete([planner, {'role': 'user', 'content':
            'Tema del relato: ' + json.dumps(theme, ensure_ascii=False) +
            '. El protagonista cuenta lo que LE pasó. Construí un conflicto específico de este tema, '
            'no una plantilla de favores, dinero o venganza. No agregues una boda, un pago ni '
            'familiares si el tema no los necesita. Cada escena cambia algo: qué sabe alguien, '
            'qué puede perder o qué decide hacer. Evitá repetir reclamos sin avanzar. '
            'El giro debe reinterpretar un detalle presentado antes, con una explicación plausible. '
            'Agregá solo los detalles indispensables donde el usuario dejó espacio. '
            'Usá estos ocho campos JSON de texto, máximo dos oraciones breves por campo: '
            'title (título concreto), narrator (quién cuenta y qué quiere), relationship '
            '(quién se opone y qué quiere; parentescos exactos del tema), grievance (hecho inicial '
            'y qué está en juego), resource (hechos fijos: quién sabe qué, de quién es cada objeto '
            'y quién tiene cada obligación), clue (detalle temprano y cómo se descubre su significado), '
            'cliffhanger (última acción de parte 1 y reacción INMEDIATA que abre parte 2), '
            'outcome (decisión final y consecuencia concreta ya ocurrida, coherente con los hechos). '
            'Ordená los hechos cronológicamente y no cambies su causa. Si alguien es excluido, '
            'no lo hagas asistir sin explicación. Máximo 220 palabras en total.' }], json_mode=True)
        data = json.loads(outline)
        fields = ('title', 'narrator', 'relationship', 'grievance', 'resource', 'clue', 'cliffhanger', 'outcome')
        if not isinstance(data, dict) or any(not isinstance(data.get(k), str) or not data[k].strip() for k in fields):
            raise ValueError('No se pudo preparar un plan completo.')
        title = data['title'].strip()
        plan = json.dumps({k: data[k] for k in fields if k != 'title'}, ensure_ascii=False)
        target = round(duration * 2.3)
        length = f'Escribí entre {round(duration * 1.7)} y {round(duration * 2.9)} palabras (objetivo: {target}). '
        common = ('TEMA ORIGINAL (tiene prioridad sobre el plan): ' + json.dumps(theme, ensure_ascii=False) +
                  '\nPLAN de los DOS episodios, sin narrarlo como resumen: ' + outline)
        first_prompt = (common + '\nEscribí SOLO la PARTE 1 EN PRIMERA PERSONA. ' + length +
                        'Abrí con el hecho más fuerte del conflicto, sin describir el clima ni una rutina. Mostrá lo que está en juego y sembrá la pista mediante acciones '
                        'narradas por una sola voz. Si citás a alguien, identificá antes quién habla. El protagonista toma una decisión. No describas la estructura del relato ni escribas '
                        '«la confrontación está pendiente», «la tensión era palpable» o «todo cambiaría». Terminá en una acción concreta del enfrentamiento '
                        'del plan, con una oración completa y antes de la reacción: el video se corta ahí. '
                        'No prometas contar algo después ni agregues una despedida. Solo prosa, sin título ni JSON.')
        progress('Escribiendo la parte 1: conflicto y suspenso…')
        part1 = write_episode([system, {'role': 'user', 'content': first_prompt}], duration, progress)
        second_prompt = ('Continuá con SOLO la PARTE 2 EN PRIMERA PERSONA. ' + length +
                         'Retomá exactamente la última escena, sin resumir el episodio anterior. '
                         'Resolvé de inmediato la acción del corte. Mostrá cómo cambia la situación y qué decide el protagonista. Usá el detalle sembrado en la primera parte; no inventes una prueba salvadora. '
                         'Cerrá mostrando una consecuencia YA OCURRIDA, no esperando que en el futuro colaboren. '
                         'No contradigas lo que cada personaje sabía en la primera parte. '
                         'Mismos nombres, género gramatical, parentescos, objetos y hechos. '
                         'Sin otra parte pendiente. Solo prosa, sin título ni JSON.')
        progress('Escribiendo la parte 2 desde el final de la primera…')
        part2 = write_episode([system, {'role': 'user', 'content': first_prompt},
                               {'role': 'assistant', 'content': part1},
                               {'role': 'user', 'content': second_prompt}], duration, progress)
        return review_and_repair(theme, {'title': title, 'plan': plan, 'part1': part1, 'part2': part2},
                                 duration, progress)
    except (ValueError, TypeError) as exc:
        raise StoryGenerationError('La historia no pasó la revisión: ' + str(exc)) from exc
    finally:
        try:
            with _request('/api/generate', {'model': MODEL, 'keep_alive': 0}, timeout=10):
                pass
        except (OSError, URLError):
            pass
