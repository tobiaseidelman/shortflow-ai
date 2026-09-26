import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.getenv("SHORTFLOW_DB_PATH", str(ROOT / "shortflow.db"))).expanduser().resolve()
DB.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass
