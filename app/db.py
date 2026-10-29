from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


if settings.database_url.startswith("sqlite"):
    # SQLite admite un escritor a la vez: se le da margen de espera para que
    # una escritura no falle cuando otro cliente está guardando.
    engine = create_async_engine(
        settings.database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )
else:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)

if settings.database_url.startswith("sqlite"):
    # Con varios clientes a la vez, SQLite necesita WAL y espera ante bloqueo:
    # sin esto aparecen "database is locked" en cuanto hay escrituras
    # simultáneas.
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _pragma_sqlite(dbapi_connection, _registro):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    if not settings.auto_create_db:
        return
    from . import models  # noqa: F401  (registra las tablas en Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
