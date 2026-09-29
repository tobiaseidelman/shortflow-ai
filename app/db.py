import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.getenv("SHORTFLOW_DB_PATH", str(ROOT / "shortflow.db"))).expanduser().resolve()
DB.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB}", connect_args={"check_same_thread": False, "timeout": 30})
# Readers must remain available while background jobs commit progress.
@event.listens_for(engine, "connect")
def configure_sqlite(connection, record):
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass
