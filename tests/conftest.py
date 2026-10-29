from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  (registra las tablas)
from app.config import settings
from app.db import Base
from app.seed import seed_demo


@pytest.fixture(autouse=True)
def force_mock_sap(monkeypatch):
    # Los tests no deben tocar el Service Layer real.
    monkeypatch.setattr(settings, "sap_mode", "mock")
    monkeypatch.setattr(settings, "sap_live_reads", False)
    monkeypatch.setattr(settings, "sap_write_enabled", False)
    monkeypatch.setattr(settings, "memory_auto_summary", False)
    # Sin espera de agrupado: los tests tienen que ser deterministas.
    monkeypatch.setattr(settings, "batching_ms", 0)


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await seed_demo(session, force=True)
        yield session
    await engine.dispose()
