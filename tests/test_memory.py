from __future__ import annotations

from app.agent import Toolbox
from app.models import Contact
from app.services import memory


async def _contact(session) -> Contact:
    contact = Contact(wa_id="59170000888", phone_e164="+59170000888", name="Ana")
    session.add(contact)
    await session.commit()
    return contact


async def test_remember_fact_requires_consent_and_is_retrieved(session):
    contact = await _contact(session)

    try:
        await memory.remember_fact(
            session, contact.id, "estilo", "moderno", consent=False
        )
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Sin consentimiento no debe guardar")

    await memory.remember_fact(
        session, contact.id, "estilo", "moderno", consent=True
    )
    text = await memory.memory_text(session, contact, "conv-1")
    assert "estilo=moderno" in text


async def test_profile_tool_returns_memory(session):
    contact = await _contact(session)
    await memory.remember_fact(
        session, contact.id, "ciudad", "Santa Cruz", consent=True
    )

    toolbox = Toolbox(session, contact)
    result = await toolbox.tool_get_customer_profile()
    assert result["ok"] is True
    assert result["profile"]["consent"] is True
    assert any(fact["key"] == "ciudad" for fact in result["facts"])


async def test_sensitive_fact_is_rejected(session):
    contact = await _contact(session)
    try:
        await memory.remember_fact(
            session,
            contact.id,
            "nota",
            "carnet 1234567",
            consent=True,
        )
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("No debe guardar datos sensibles")
