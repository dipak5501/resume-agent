import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import db
from app.core import config


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Every test gets a fresh temp SQLite DB + data dir (T11). Reconfigures the
    db module globals so all code paths (routers, storage) use the temp store."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    url = f"sqlite:///{tmp_path / 'app.db'}"
    monkeypatch.setattr(config, "DB_URL", url)
    engine = create_engine(url, connect_args={"check_same_thread": False})
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    db.init_db()
    yield
