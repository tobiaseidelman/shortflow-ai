"""Opt-in real-model check: downloads ~4.7 GB, never calls a paid API."""
import json
import sys
from pathlib import Path
import tempfile

from app import story_engine
from app.story_engine import generate_story, stop_server


if __name__ == '__main__':
    if '--gemma' in sys.argv:
        story_engine.MODEL = 'gemma3:4b'
    print('Modelo en prueba:', story_engine.MODEL, flush=True)
    original_complete = story_engine.complete
    def inspect_call(messages, json_mode=False):
        response = original_complete(messages, json_mode)
        print('Respuesta de etapa:', response, flush=True)
        return response
    story_engine.complete = inspect_call
    original_validate = story_engine.validate_story
    def inspect_sample(data, duration):
        print('Borrador de prueba:', json.dumps(data, ensure_ascii=False), flush=True)
        return original_validate(data, duration)
    story_engine.validate_story = inspect_sample
    try:
        with tempfile.TemporaryDirectory(prefix='shortflow-model-') as storage:
            result = generate_story(
                'Mi hermano me pidió que pagara el catering de su boda. Una semana antes descubrí '
                'que no estaba invitado porque su novia se avergonzaba de mi trabajo pintando casas. '
                'Ya pagué la seña, falta el saldo y el contrato está a nombre de él. '
                'Cuando me negué a pagar el resto vino a mi casa con nuestros padres para presionarme.',
                90, Path(storage), lambda message: print(message, flush=True))
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
            stop_server()
    finally:
        stop_server()
