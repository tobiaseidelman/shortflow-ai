#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
if [[ -x .venv/bin/python ]]; then
  PYTHON="$PWD/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi
"$PYTHON" -c 'import sys; sys.exit("Se requiere Python 3.12 o superior.") if sys.version_info < (3, 12) else None'
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Falta FFmpeg. Reconstruí el contenedor de Codespaces o instalá FFmpeg en PATH." >&2
  exit 1
fi
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
exec "$PYTHON" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
