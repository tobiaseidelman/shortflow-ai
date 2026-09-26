"""Keep all test data outside the user's database and video folders."""
import os
import tempfile
from pathlib import Path

_data = tempfile.TemporaryDirectory(prefix="shortflow-tests-")
os.environ["SHORTFLOW_DB_PATH"] = str(Path(_data.name) / "shortflow.db")
os.environ["SHORTFLOW_STORAGE_DIR"] = str(Path(_data.name) / "storage")


def pytest_unconfigure(config):
    from app.db import engine
    engine.dispose()
    _data.cleanup()
