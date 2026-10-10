import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    DB_PATH = os.environ.get("AB_TEST_DB_PATH", "voice_ab.db")
    DATABASE_URL = f"sqlite:///{DB_PATH}"
elif DATABASE_URL.startswith("postgres://"):
    # SQLAlchemy requires postgresql:// instead of postgres://
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from db import models
    Base.metadata.create_all(bind=engine)
    # SQLite create_all does not alter an existing table. Keep local/demo
    # databases created before configurable dispositions usable.
    columns = {column["name"] for column in inspect(engine).get_columns("experiments")}
    if "primary_disposition" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE experiments ADD COLUMN primary_disposition VARCHAR(128) NOT NULL DEFAULT 'BL Enriched'")
            )
    experiment_columns = {column["name"] for column in inspect(engine).get_columns("experiments")}
    with engine.begin() as connection:
        if "started_at" not in experiment_columns:
            connection.execute(text("ALTER TABLE experiments ADD COLUMN started_at DATETIME"))
        if "deployed_variant_key" not in experiment_columns:
            connection.execute(text("ALTER TABLE experiments ADD COLUMN deployed_variant_key VARCHAR(8)"))
    event_columns = {column["name"] for column in inspect(engine).get_columns("call_events")}
    if "duration_observed" not in event_columns:
        with engine.begin() as connection:
            # Old demo durations were derived from record timestamps, not audio.
            connection.execute(text("ALTER TABLE call_events ADD COLUMN duration_observed BOOLEAN NOT NULL DEFAULT 0"))
