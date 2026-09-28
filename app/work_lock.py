"""Avoid loading a story model and rendering video simultaneously on small Codespaces."""
from threading import Lock
compute_lock = Lock()
