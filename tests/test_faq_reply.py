"""FAQ: con un artículo publicado se responde sin gastar un turno del LLM."""

from __future__ import annotations

from app.agent import Agent
from app.models import Contact
from app.services import knowledge as knowledge_service


async def test_faq_responde_desde_conocimiento_sin_llm(session, monkeypatch):
    monkeypatch.setattr(
        knowledge_service,
        "search",
        lambda query, limit=3: [
            {
                "title": "Política de cambios",
                "content": "Tenés 30 días para cambiar el producto sin uso.",
                "tags": ["cambio"],
                "source": "test",
            }
        ],
    )

    agent = Agent()

    def boom(*args, **kwargs):  # pragma: no cover - sólo si se llama
        raise AssertionError("no debería llamar al LLM")

    agent._llm = boom  # type: ignore[method-assign]

    contact = Contact(wa_id="59170000701", phone_e164="+59170000701", name="Ana")
    session.add(contact)
    await session.commit()

    reply = await agent.handle(session, contact, "tienen politica de cambios?")

    text = reply.messages[0].text
    assert "30 días" in text
    assert "Política de cambios" in text


async def test_faq_sin_articulos_va_al_llm(session, monkeypatch):
    monkeypatch.setattr(knowledge_service, "search", lambda query, limit=3: [])

    agent = Agent()
    llamado = {"llm": False}

    async def fake_llm_handle(*args, **kwargs):
        llamado["llm"] = True
        from app.agent import AgentReply, Outbound

        return AgentReply([Outbound(text="respuesta del modelo")])

    agent._llm_handle = fake_llm_handle  # type: ignore[method-assign]

    contact = Contact(wa_id="59170000702", phone_e164="+59170000702", name="Ana")
    session.add(contact)
    await session.commit()

    reply = await agent.handle(session, contact, "hacen envios a domicilio?")

    assert llamado["llm"] is True
    assert "modelo" in reply.messages[0].text
