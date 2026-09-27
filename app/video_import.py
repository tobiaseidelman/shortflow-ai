"""Import one public YouTube video into a temporary directory, without credentials."""
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

MAX_BYTES = 1024 ** 3
MAX_SECONDS = 2 * 60 * 60
SEGMENT_SECONDS = 10 * 60


class ImportFailure(Exception):
    pass


def youtube_url(value):
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or parsed.port:
            raise ValueError
        host = (parsed.hostname or '').lower()
        pieces = parsed.path.strip('/').split('/')
        if host == 'youtu.be' and len(pieces) == 1:
            video_id = pieces[0]
        elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
            if parsed.path == '/watch':
                video_id = parse_qs(parsed.query).get('v', [''])[0]
            elif len(pieces) == 2 and pieces[0] in ('shorts', 'embed', 'live'):
                video_id = pieces[1]
            else:
                raise ValueError
        else:
            raise ValueError
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            raise ValueError
    except (ValueError, TypeError):
        raise ImportFailure('Pegá el enlace de un video individual de YouTube o youtu.be.')
    return 'https://www.youtube.com/watch?v=' + video_id


def explain_download_error(detail):
    lower = detail.lower()
    if any(word in lower for word in ('sign in', 'not a bot', 'cookies', 'login', 'private video', 'age-restricted')):
        return 'YouTube pide iniciar sesión o verificar el acceso desde este equipo. No se pudo descargar. Podés subir el archivo de video directamente.'
    if any(word in lower for word in ('drm', 'copyright', 'not available', 'unavailable', 'geo restricted')):
        return 'YouTube no permite acceder a este video desde el entorno actual. Probá otro video público o subí el archivo.'
    if '403' in lower or '429' in lower:
        return 'YouTube rechazó la descarga desde esta conexión. Probá más tarde o subí el archivo de video.'
    return 'No se pudo descargar el video. Revisá que sea público y que haya conexión; también podés subir el archivo.'


def download_video(url, directory):
    url = youtube_url(url)
    directory = Path(directory)
    command = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-playlist',
               '--no-progress', '--no-cache-dir', '--js-runtimes', 'node',
               '--socket-timeout', '20', '--retries', '1', '--fragment-retries', '1',
               '--extractor-retries', '1', '--max-filesize', str(MAX_BYTES),
               '--match-filters', f'!is_live & duration > 0 & duration <= {MAX_SECONDS}',
               '--download-sections', f'*0-{SEGMENT_SECONDS}',
               '--format', 'bv[height<=720][ext=mp4][vcodec^=avc]/b[height<=720][ext=mp4]/bv[height<=720]/b[height<=720]',
               '--write-info-json', '--no-simulate', '--output', str(directory / 'source.%(ext)s'), url]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1200)
    except subprocess.TimeoutExpired as exc:
        raise ImportFailure('La descarga superó 20 minutos. Probá un video más corto o subí el archivo.') from exc
    if result.returncode:
        raise ImportFailure(explain_download_error(result.stderr))
    metadata_file = directory / 'source.info.json'
    paths = [p for p in directory.glob('source.*') if p.suffix in ('.mp4', '.webm', '.mkv', '.mov')]
    if len(paths) != 1 or not metadata_file.exists():
        raise ImportFailure('No se descargó un video válido. El límite es 2 horas y 1 GB; no se admiten transmisiones en vivo.')
    path = paths[0]
    info = json.loads(metadata_file.read_text())
    if path.stat().st_size > MAX_BYTES or not 0 < float(info.get('duration') or 0) <= MAX_SECONDS:
        raise ImportFailure('El video supera el límite de 2 horas o 1 GB.')
    return path, str(info.get('title') or 'Video de YouTube')[:255]
