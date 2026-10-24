"""Memoria de preferencias del cliente.

Guarda lo que el cliente ya dijo (medida, presupuesto, rubro) para no volver a
preguntarlo y para afinar las búsquedas. Vive en `customer_profiles.preferences`.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contact, CustomerProfile

logger = logging.getLogger(__name__)

SIZE_RE = re.compile(r"\b(\d(?:[.,]\d)?)\s*(?:plazas?|plz)\b", re.IGNORECASE)
BUDGET_RE = re.compile(
    r"(?:hasta|m[áa]ximo|menos de|presupuesto(?:\s+de)?|no m[áa]s de|"
    r"tope de)\s*(?:bs\.?|bolivianos)?\s*(\d[\d.,]*)",
    re.IGNORECASE,
)
BED_TERMS = (
    "colchon", "colchón", "cama", "almohada", "sommier", "respaldo",
    "base de cama", "box",
)


def _fold(text: str) -> str:
    return (text or "").lower().replace("á", "a").replace("é", "e").replace(
        "í", "i"
    ).replace("ó", "o").replace("ú", "u")


def extract(text: str | None) -> dict:
    """Lo que se puede aprender de un mensaje (sin inventar)."""
    folded = _fold(text)
    learned: dict = {}

    size = SIZE_RE.search(folded)
    if size:
        value = size.group(1).replace(",", ".")
        learned["size"] = f"{value} plazas"
        learned["scope"] = "colchones"

    budget = BUDGET_RE.search(folded)
    if budget:
        raw = budget.group(1).replace(".", "").replace(",", "")
        try:
            amount = int(float(raw))
        except ValueError:
            amount = 0
        if amount > 0:
            learned["budget_max"] = amount

    if any(term in folded for term in BED_TERMS):
        learned["scope"] = "colchones"

    return learned


async def _profile(
    session: AsyncSession, contact: Contact
) -> CustomerProfile:
    profile = await session.scalar(
        select(CustomerProfile).where(
            CustomerProfile.contact_id == contact.id
        )
    )
    if profile is None:
        profile = CustomerProfile(contact_id=contact.id, preferences={})
        session.add(profile)
        await session.flush()
    return profile


async def remember(
    session: AsyncSession, contact: Contact, text: str | None
) -> dict:
    """Actualiza y devuelve las preferencias conocidas del cliente."""
    learned = extract(text)
    profile = await _profile(session, contact)
    current = dict(profile.preferences or {})
    if learned:
        current.update(learned)
        profile.preferences = current
        await session.commit()
    return current


async def known(session: AsyncSession, contact: Contact) -> dict:
    profile = await session.scalar(
        select(CustomerProfile).where(
            CustomerProfile.contact_id == contact.id
        )
    )
    return dict(profile.preferences or {}) if profile else {}


def summary(preferences: dict | None) -> str | None:
    """Texto corto para el prompt: lo que ya sabemos y no hay que preguntar."""
    prefs = preferences or {}
    parts = []
    if prefs.get("size"):
        parts.append(f"medida {prefs['size']}")
    if prefs.get("budget_max"):
        parts.append(f"presupuesto hasta Bs {prefs['budget_max']}")
    if prefs.get("scope"):
        parts.append(f"le interesa {prefs['scope']}")
    if not parts:
        return None
    return "Datos ya dichos por el cliente: " + "; ".join(parts) + ". No los vuelvas a preguntar."


def enrich(query: str | None, preferences: dict | None) -> str:
    """Suma la medida recordada a una búsqueda de colchones."""
    prefs = preferences or {}
    text = (query or "").strip()
    if not text or not prefs.get("size"):
        return text
    folded = _fold(text)
    if "plaza" in folded:
        return text
    if not any(term in folded for term in BED_TERMS):
        return text
    return f"{text} {prefs['size']}"
