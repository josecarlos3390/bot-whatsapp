"""Envía encuestas de feedback vencidas usando plantilla aprobada."""

from __future__ import annotations

import asyncio
import logging

from app.db import SessionLocal, init_db
from app.runtime import whatsapp
from app.services.feedback_outbound import send_due_surveys


async def run(limit: int = 20) -> None:
    await init_db()
    async with SessionLocal() as session:
        result = await send_due_surveys(session, whatsapp, limit=limit)
    logging.info("Encuestas: %s", result)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
