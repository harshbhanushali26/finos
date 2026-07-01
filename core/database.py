"""
FinOS — database engine and session factory (core/database.py)

Responsibilities:
- Create the SQLite engine with WAL mode for concurrent reads
- Provide get_session() generator for FastAPI dependency injection
- create_db() called once at startup to create all tables

Nothing else lives here — no queries, no business logic.
"""


from sqlmodel import SQLModel, Session, create_engine

from config import DB_PATH


# ── Engine ─────────────────────────────────────────────────────────────────
# check_same_thread=False required for FastAPI (async handlers use threads)
# WAL mode: allows concurrent reads while a write is in progress

connect_args = {"check_same_thread": False}

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args=connect_args,
    echo=False                  # True for Debug SQL
)


def _enable_wal(connection, _record):
    """Enable WAL journal mode on every new connection."""
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA foreign_keys=ON;")


# Register WAL pragma on connect

from sqlalchemy import event
event.listen(engine.sync_engine if hasattr(engine, "sync_engine") else engine, "connect", _enable_wal)


# ── Session factory ────────────────────────────────────────────────────────


def get_session():
    """
    FastAPI dependency. Yields a database session and closes it after the
    request finishes, whether it succeeded or raised an exception.

    Usage in a route:
        @router.get("/example")
        def example(db: Session = Depends(get_session)):
            ...
    """
    with Session(engine) as session:
        yield session


# ── Startup ────────────────────────────────────────────────────────────────

def create_db():
    """
    Create all SQLModel tables if they don't exist.
    Called once from api/main.py on startup.
    Safe to call multiple times — create_all is idempotent.
    """
    # Import models here to ensure they are registered with SQLModel metadata
    import core.models
    SQLModel.metadata.create_all(engine)