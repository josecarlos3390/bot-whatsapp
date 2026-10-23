"""Usuarios de área para el centro de reglas."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AreaUser
from . import advisors as advisor_service
from .area_rules import AREAS


class AreaUserError(ValueError):
    pass


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    area: str,
    display_name: str | None = None,
) -> AreaUser:
    username = (username or "").strip().lower()
    if not username or not password:
        raise AreaUserError("Usuario y contraseña son obligatorios")
    if area not in AREAS:
        raise AreaUserError(f"Área inválida: {area}")
    if await get_by_username(session, username) is not None:
        raise AreaUserError("Ese usuario ya existe")
    user = AreaUser(
        username=username,
        display_name=(display_name or username).strip()[:120],
        password_hash=advisor_service.hash_password(password),
        area=area,
        active=True,
    )
    session.add(user)
    await session.commit()
    return user


async def get_by_username(
    session: AsyncSession, username: str
) -> AreaUser | None:
    return await session.scalar(
        select(AreaUser).where(
            AreaUser.username == username.strip().lower(),
            AreaUser.active.is_(True),
        )
    )


async def authenticate(
    session: AsyncSession, username: str, password: str
) -> AreaUser | None:
    user = await get_by_username(session, username)
    if user is None or not advisor_service.verify_password(
        password, user.password_hash
    ):
        return None
    return user


async def list_users(session: AsyncSession) -> list[AreaUser]:
    return list(
        (
            await session.scalars(
                select(AreaUser).order_by(AreaUser.area, AreaUser.username)
            )
        ).all()
    )


async def update_user(
    session: AsyncSession,
    user: AreaUser,
    *,
    display_name: str | None = None,
    area: str | None = None,
    active: bool | None = None,
    password: str | None = None,
) -> AreaUser:
    if display_name is not None:
        user.display_name = display_name.strip()[:120] or user.username
    if area is not None:
        if area not in AREAS:
            raise AreaUserError(f"Área inválida: {area}")
        user.area = area
    if active is not None:
        user.active = active
    if password is not None:
        if len(password) < 8:
            raise AreaUserError("La contraseña debe tener al menos 8 caracteres")
        user.password_hash = advisor_service.hash_password(password)
    await session.commit()
    return user
