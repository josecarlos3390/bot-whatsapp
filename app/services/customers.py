"""Identificación de clientes por carnet/NIT en SAP.

En el Service Layer, el campo ``LicTradNum`` del dato maestro se expone como
``FederalTaxID``. Se consulta solo con consentimiento y no se persiste el
documento: únicamente se vincula ``contact_id`` con ``CardCode``.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Contact, Conversation, CustomerCandidate, Message
from ..sap import ServiceLayerSap, get_sap
from . import vtex_customers
from .purchases import history_summary, sync_contact_purchases

logger = logging.getLogger(__name__)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _mask_name(name: str) -> str:
    parts = [part for part in (name or "").split() if part]
    return " ".join(part[0] + "***" for part in parts[:4])


async def find_by_document(
    sap: ServiceLayerSap, document: str, limit: int = 5
) -> list[dict]:
    raw = (document or "").strip()
    variants = [raw]
    digits = _digits(raw)
    if digits and digits != raw:
        variants.append(digits)
    seen: set[str] = set()
    candidates: list[dict] = []
    for value in variants:
        escaped = value.replace("'", "''")
        data = await sap.get(
            "BusinessPartners",
            params={
                "$filter": f"FederalTaxID eq '{escaped}'",
                "$top": limit,
                "$select": (
                    "CardCode,CardName,CardType,FederalTaxID,"
                    "Cellular,Phone1,EmailAddress"
                ),
            },
        )
        for bp in data.get("value", []):
            code = bp.get("CardCode")
            if not code or code in seen:
                continue
            seen.add(code)
            candidates.append(
                {
                    "card_code": code,
                    "name": bp.get("CardName"),
                    "name_masked": _mask_name(bp.get("CardName") or ""),
                    "card_type": bp.get("CardType"),
                    "has_phone": bool(
                        bp.get("Cellular") or bp.get("Phone1")
                    ),
                    "has_email": bool(bp.get("EmailAddress")),
                }
            )
            if len(candidates) >= limit:
                return candidates
    return candidates


async def save_candidates(
    session: AsyncSession, contact_id: str, candidates: list[dict]
) -> None:
    await session.execute(
        delete(CustomerCandidate).where(
            CustomerCandidate.contact_id == contact_id
        )
    )
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    for candidate in candidates:
        session.add(
            CustomerCandidate(
                contact_id=contact_id,
                card_code=candidate["card_code"],
                name=candidate.get("name"),
                name_masked=candidate.get("name_masked"),
                expires_at=expires,
            )
        )
    await session.commit()


async def pending_candidate(
    session: AsyncSession, contact_id: str, card_code: str | None = None
) -> CustomerCandidate | None:
    stmt = select(CustomerCandidate).where(
        CustomerCandidate.contact_id == contact_id,
        CustomerCandidate.expires_at >= datetime.now(timezone.utc),
    )
    if card_code:
        stmt = stmt.where(CustomerCandidate.card_code == card_code)
    return await session.scalar(stmt.order_by(CustomerCandidate.created_at.desc()))


async def redact_document(
    session: AsyncSession, contact_id: str, document: str
) -> None:
    """Reemplaza el documento en los mensajes guardados del cliente."""
    variants = {
        (document or "").strip(),
        _digits(document),
    }
    variants.discard("")
    if not variants:
        return
    rows = (
        await session.scalars(
            select(Message)
            .join(
                Conversation,
                Conversation.id == Message.conversation_id,
            )
            .where(
                Conversation.contact_id == contact_id,
                Message.direction == "in",
            )
            .order_by(Message.created_at.desc())
            .limit(10)
        )
    ).all()
    changed = False
    for row in rows:
        text = row.text or ""
        new_text = text
        for variant in variants:
            if variant and variant in new_text:
                new_text = new_text.replace(variant, "[documento]")
        if new_text != text:
            row.text = new_text
            changed = True
    if changed:
        await session.commit()


async def link_customer(
    session: AsyncSession,
    contact: Contact,
    card_code: str,
    *,
    document: str | None = None,
) -> dict:
    """Vincula el contacto con el CardCode y sincroniza sus compras."""
    code = (card_code or "").strip()
    if not code:
        raise ValueError("Falta el CardCode.")
    candidate = await pending_candidate(session, contact.id, code)
    if candidate is None:
        raise ValueError(
            "El CardCode no coincide con la identificación pendiente. "
            "Pedile el carnet/NIT de nuevo."
        )
    contact.sap_card_code = code
    if settings.sap_mode == "vtex":
        contact.tax_id = code[:20]
    await session.commit()

    if settings.sap_mode == "vtex":
        sap = get_sap(session)
        try:
            inserted = await vtex_customers.sync_contact(
                session,
                contact,
                sap,
                document=document or code,
            )
        finally:
            await sap.close()
    else:
        sap = ServiceLayerSap(session)
        try:
            inserted = await sync_contact_purchases(session, contact, sap)
        finally:
            await sap.close()

    await session.execute(
        delete(CustomerCandidate).where(
            CustomerCandidate.contact_id == contact.id
        )
    )
    await session.commit()
    if document:
        await redact_document(session, contact.id, document)
    summary = await history_summary(session, contact.id)
    logger.info(
        "Cliente %s vinculado a %s (%s compras)",
        contact.wa_id,
        code,
        inserted,
    )
    return {
        "ok": True,
        "card_code": code,
        "purchases_synced": inserted,
        "summary": summary,
    }
