"""Crea un asesor de la bandeja."""

from __future__ import annotations

import argparse
import asyncio

from app.db import SessionLocal, init_db
from app.services.advisors import create_advisor


async def run(
    username: str, password: str, display_name: str | None, is_admin: bool
) -> None:
    await init_db()
    async with SessionLocal() as session:
        advisor = await create_advisor(
            session, username, password, display_name, is_admin=is_admin
        )
        print(f"Asesor creado: {advisor.username} ({advisor.display_name})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--admin", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        run(args.username, args.password, args.name or None, args.admin)
    )


if __name__ == "__main__":
    main()
