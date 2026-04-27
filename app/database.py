from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import BACKEND_DIR, settings


def _resolve_database_url(url: str) -> str:
    if not url.startswith("sqlite:///./"):
        return url

    relative_path = url.removeprefix("sqlite:///./")
    resolved_path = (BACKEND_DIR / relative_path).resolve()
    return f"sqlite:///{resolved_path.as_posix()}"


DATABASE_URL = _resolve_database_url(settings.DATABASE_URL)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that provides a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Schema is managed by Alembic migrations."""
    return None
