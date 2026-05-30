from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATABASE_URL = f"sqlite:///{DATA_DIR / 'app.db'}"


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    from app.models import ApiKey, Audit, Secret

    Base.metadata.create_all(bind=engine)
