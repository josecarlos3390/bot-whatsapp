"""Advisor authentication with password hashing and signed sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Advisor

PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, digest = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("ascii"),
            int(iterations),
        ).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False


def _sign(value: str) -> str:
    return hmac.new(
        settings.advisor_session_secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def make_session(username: str) -> str:
    expires = int(
        (
            datetime.now(timezone.utc)
            + timedelta(hours=settings.advisor_session_hours)
        ).timestamp()
    )
    payload = base64.urlsafe_b64encode(
        f"{username}|{expires}".encode("utf-8")
    ).decode("ascii")
    return f"{payload}.{_sign(payload)}"


def parse_session(token: str) -> str | None:
    try:
        payload, signature = token.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(_sign(payload), signature):
        return None
    try:
        username, expires = base64.urlsafe_b64decode(payload).decode().split("|")
    except (ValueError, UnicodeDecodeError):
        return None
    if int(expires) < int(datetime.now(timezone.utc).timestamp()):
        return None
    return username


async def create_advisor(
    session: AsyncSession,
    username: str,
    password: str,
    display_name: str | None = None,
    *,
    is_admin: bool = False,
    role: str | None = None,
) -> Advisor:
    chosen_role = role or ("admin" if is_admin else "agent")
    if chosen_role not in {"admin", "supervisor", "agent"}:
        raise ValueError("Rol inválido")
    advisor = Advisor(
        username=username.strip().lower(),
        display_name=(display_name or username).strip()[:120],
        password_hash=hash_password(password),
        active=True,
        is_admin=chosen_role == "admin",
        role=chosen_role,
    )
    session.add(advisor)
    await session.commit()
    return advisor


async def set_password(
    session: AsyncSession, advisor: Advisor, password: str
) -> None:
    advisor.password_hash = hash_password(password)
    await session.commit()


async def list_advisors(session: AsyncSession) -> list[Advisor]:
    return list(
        (
            await session.scalars(
                select(Advisor).order_by(Advisor.display_name)
            )
        ).all()
    )


async def on_duty_advisors(session: AsyncSession) -> list[Advisor]:
    return list(
        (
            await session.scalars(
                select(Advisor)
                .where(Advisor.active.is_(True), Advisor.on_duty.is_(True))
                .order_by(Advisor.display_name)
            )
        ).all()
    )


async def authenticate(
    session: AsyncSession, username: str, password: str
) -> Advisor | None:
    advisor = await session.scalar(
        select(Advisor).where(
            Advisor.username == username.strip().lower(),
            Advisor.active.is_(True),
        )
    )
    if advisor is None or not verify_password(password, advisor.password_hash):
        return None
    return advisor


async def current_advisor(
    session: AsyncSession, username: str
) -> Advisor | None:
    return await session.scalar(
        select(Advisor).where(
            Advisor.username == username, Advisor.active.is_(True)
        )
    )
