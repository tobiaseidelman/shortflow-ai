"""Opt-in real-model check: downloads ~3.4 GB, never calls a paid API."""
import json
from pathlib import Path
import tempfile

from app.story_engine import generate_story, stop_server


if __name__ == '__main__':
    try:
        with tempfile.TemporaryDirectory(prefix='shortflow-model-') as storage:
            result = generate_story(
                'Mi hermana se atribuye mi trabajo organizando un evento familiar y me excluye de él. '
                'El giro debe ser verosímil y permitir entender una pista de la primera parte.',
                90, Path(storage), lambda message: print(message, flush=True))
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
            stop_server()
    finally:
        stop_server()
