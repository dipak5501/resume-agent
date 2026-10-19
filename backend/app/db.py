"""SQLAlchemy engine/session/Base (T11). SQLite now; DATABASE_URL flips it to
Postgres later with no code change. Sync — SQLite serializes writes, so async
buys nothing at this scale (ponytail)."""

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core import config

_connect_args = {"check_same_thread": False} if config.DB_URL.startswith("sqlite") else {}
engine = create_engine(config.DB_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as s:
        yield s


def _add_missing_columns(model) -> None:
    """create_all never ALTERs an existing table, so add any columns declared on
    the model but missing from the db file. ponytail: dev-grade additive
    migration for nullable columns (SQLite/Postgres ADD COLUMN) — swap for
    Alembic when a real deploy needs versioned, reversible migrations."""
    table = model.__tablename__
    have = {c["name"] for c in inspect(engine).get_columns(table)}
    with engine.begin() as conn:
        for col in model.__table__.columns:
            if col.name not in have:
                coltype = col.type.compile(engine.dialect)
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN "{col.name}" {coltype}'))


def _create_missing_indexes() -> None:
    """create_all builds a table's indexes only when it creates the table, so an
    index added to an existing model would never appear on an existing db file.
    ponytail: same dev-grade migration posture as _add_missing_columns."""
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            index.create(bind=engine, checkfirst=True)


def init_db() -> None:
    """Create tables and seed the single profile_id='default' row + the answer-
    bank canonical core (T13). Idempotent."""
    from app import models  # noqa: F401 — register mappers before create_all
    from app.canonical import ANSWER_CANONICAL

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    _add_missing_columns(models.Profile)  # dev-grade migration for an existing db file
    _add_missing_columns(models.TrackedCompany)  # T29: gone_at
    _add_missing_columns(models.JobPosting)  # T46: first_seen_at
    _create_missing_indexes()  # create_all only builds indexes alongside a NEW table
    with SessionLocal() as s:
        if s.get(models.Profile, "default") is None:
            s.add(models.Profile(id="default"))
        have = {a.canonical for a in s.scalars(
            select(models.Answer).where(models.Answer.profile_id == "default")
        )}
        for canon, mode in ANSWER_CANONICAL.items():
            if canon not in have:  # seed empty, pre-flagged mode; user fills it later
                s.add(models.Answer(profile_id="default", canonical=canon, mode=mode, answer=""))
        s.commit()
