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
_server = None
_http = build_opener(ProxyHandler({}))
SCHEMA = {
    'type': 'object',
    'properties': {key: {'type': 'string'} for key in ('title', 'plan', 'part1', 'part2')},
    'required': ['title', 'plan', 'part1', 'part2'],
    'additionalProperties': False,
}
SYSTEM = """Escribís relatos originales de ficción en español natural, estilo confesión de Reddit.
El narrador cuenta su propia experiencia EN PRIMERA PERSONA: yo, me, mi.
Conservá su identidad y género gramatical, también en los diálogos.
Usá hechos cotidianos, diálogos claros y consecuencias creíbles. Nada de accidentes
convenientes, fortunas repentinas, documentos mágicos ni personajes nuevos que solucionan todo.
Respetá el plan y los hechos anteriores. Cada escena debe aportar algo nuevo.

Referencia de técnica narrativa (NO copies personajes, conflicto, objetos ni frases):
PARTE 1 DE EJEMPLO:
«Vos vení temprano y después te vas», me dijo mi primo. Acababa de pedirme mi camioneta
para llevar las mesas de su fiesta. En el grupo vi que todos estaban invitados menos yo.
Cuando pregunté, contestó que necesitaba alguien que trabajara, no otro invitado.
Yo había cambiado mi turno para ayudarlo. Las mesas las alquiló él; la camioneta era mía.
Le avisé que no haría el traslado y volví a tomar mi turno. No cancelé ninguna reserva
ajena ni escondí nada. Le quedaban dos días para contratar un flete. El sábado, mientras
me ponía el uniforme, escuché su voz en el portero: había venido con los amigos a buscar
las llaves. Bajé sin ellas.
PARTE 2 DE EJEMPLO:
Mi primo miró mis manos vacías. Primero dijo que era una broma; después, que el flete
costaba demasiado. Le mostré el mensaje donde me había pedido irme antes de la fiesta.
«Entonces vení, pero llevá las mesas», respondió. No quería invitarme: quería el viaje.
Me dolió admitirlo delante de sus amigos. Uno de ellos se ofreció a buscar otro flete.
Mi primo terminó pagándolo y yo llegué a trabajar a horario. Esa noche me mandó una foto
de las mesas instaladas y escribió que le debía una disculpa. No discutí: le respondí
que podía contar conmigo como primo, pero que cualquier otro traslado tendría que
pedírmelo sin condiciones escondidas. Guardé el teléfono. Las llaves seguían conmigo.

Aplicá esa precisión causal a una historia DISTINTA según el tema del usuario. No uses
objetos misteriosos sin función ni conversaciones circulares. Mostrá el resultado final."""


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
                   OLLAMA_NUM_PARALLEL='1', OLLAMA_MAX_LOADED_MODELS='1')
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
        'options': {'temperature': 0.65, 'num_ctx': 8192, 'num_predict': 1800,
                    'seed': secrets.randbelow(2**31)},
    }
    if json_mode:
        payload['format'] = 'json'
    try:
        with _request('/api/chat', payload, timeout=600) as response:
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
        if any(term in str(detail).lower() for term in ('memory', 'out of memory', 'allocate', 'oom')):
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
                instruction = f'Ampliá el texto a unas {target} palabras desarrollando acciones y diálogo, sin repetir hechos.'
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



def generate_story(theme, duration, storage, progress):
    ensure_model(storage, progress)
    system = {'role': 'system', 'content': SYSTEM}
    progress('Planificando el conflicto, el corte y el desenlace…')
    try:
        # Planning has its own brief instruction: a prose example can distract a
        # small model into copying objects or inventing unrelated twists.
        planner = {'role': 'system', 'content':
            'Sos guionista de relatos cotidianos. Diseñá una sola cadena de causa y efecto, '
            'con dos protagonistas adultos y un conflicto fácil de entender. '
            'No escribas prosa todavía. Respondé solo el JSON solicitado.'}
        outline = complete([planner, {'role': 'user', 'content':
            'Tema del relato: ' + json.dumps(theme, ensure_ascii=False) +
            '. El protagonista cuenta lo que LE pasó. Alguien lo menosprecia, pero sigue '
            'necesitando un aporte concreto suyo. El protagonista pone un límite razonable, '
            'avisa antes y deja de hacer ese favor. La otra persona intenta convencerlo; '
            'él sostiene el límite y vemos qué tuvo que hacer la otra persona en su lugar. '
            'El giro consiste en descubrir ese aporte subestimado, no en un objeto misterioso. '
            'No uses listas de invitados, flores ni preferencias de decoración como recurso. '
            'Sin sabotajes, castigos desproporcionados ni nuevos conflictos al final. '
            'Usá estos ocho campos JSON de texto, máximo una oración breve por campo: '
            'title (título), narrator (nombre y género del protagonista), relationship '
            '(nombre y relación de la otra persona), grievance (agravio concreto), '
            'resource (qué favor o trabajo controla legítimamente el protagonista), '
            'clue (acción temprana que muestra quién hace ese trabajo), cliffhanger '
            '(la otra persona llega a reclamar ese favor al final de la parte 1), '
            'outcome (qué solución alternativa pagó o hizo la otra persona tras el NO definitivo). '
            'Todos los campos deben tratar del MISMO aporte. Si fue excluido de un evento, '
            'el protagonista no asiste de pronto a él. Máximo 150 palabras en total.'}], json_mode=True)
        data = json.loads(outline)
        fields = ('title', 'narrator', 'relationship', 'grievance', 'resource', 'clue', 'cliffhanger', 'outcome')
        if not isinstance(data, dict) or any(not isinstance(data.get(k), str) or not data[k].strip() for k in fields):
            raise ValueError('No se pudo preparar un plan completo.')
        title = data['title'].strip()
        plan = json.dumps({k: data[k] for k in fields if k != 'title'}, ensure_ascii=False)
        target = round(duration * 2.3)
        length = f'Escribí entre {round(duration * 1.7)} y {round(duration * 2.9)} palabras (objetivo: {target}). '
        common = 'Este es el plan de los DOS episodios, no lo narres como un resumen: ' + outline
        first_prompt = (common + '\nEscribí SOLO la PARTE 1 EN PRIMERA PERSONA. ' + length +
                        'Abrí con el agravio concreto, mostrá el aporte ignorado y la pista mediante acciones '
                        'y diálogo. El protagonista toma una decisión. No describas la estructura del relato ni escribas '
                        '«la confrontación está pendiente», «la tensión era palpable» o «todo cambiaría». Terminá en una acción concreta del enfrentamiento '
                        'pendiente del plan, sin resolverlo todavía. Solo prosa, sin título ni JSON.')
        progress('Escribiendo la parte 1: conflicto y suspenso…')
        part1 = write_episode([system, {'role': 'user', 'content': first_prompt}], duration, progress)
        second_prompt = ('Continuá con SOLO la PARTE 2 EN PRIMERA PERSONA. ' + length +
                         'Retomá exactamente la última escena, sin resumir el episodio anterior. '
                         'Mostrá el enfrentamiento prometido, la negociación y la decisión final del plan. '
                         'Cerrá mostrando una consecuencia YA OCURRIDA, no esperando que en el futuro colaboren. '
                         'No contradigas lo que cada personaje sabía en la primera parte. '
                         'Mismos nombres, género gramatical, parentescos, objetos y hechos. '
                         'Sin otra parte pendiente. Solo prosa, sin título ni JSON.')
        progress('Escribiendo la parte 2 desde el final de la primera…')
        part2 = write_episode([system, {'role': 'user', 'content': first_prompt},
                               {'role': 'assistant', 'content': part1},
                               {'role': 'user', 'content': second_prompt}], duration, progress)
        return validate_story({'title': title, 'plan': plan, 'part1': part1, 'part2': part2}, duration)
    except (ValueError, TypeError) as exc:
        raise StoryGenerationError('La historia no pasó la revisión: ' + str(exc)) from exc
    finally:
        try:
            with _request('/api/generate', {'model': MODEL, 'keep_alive': 0}, timeout=10):
                pass
        except (OSError, URLError):
            pass
