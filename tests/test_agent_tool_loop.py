"""El LLM no debe dejar al cliente sin respuesta cuando insiste con herramientas."""

from __future__ import annotations

from types import SimpleNamespace

from app.agent import Agent
from app.models import Contact


class _FakeCompletions:
    """Devuelve tool_calls las primeras veces y un cierre en la última."""

    def __init__(self, final_text: str | None, rounds: int = 4) -> None:
        self.final_text = final_text
        self.rounds = rounds
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.rounds:
            call = SimpleNamespace(
                id=f"call_{self.calls}",
                type="function",
                function=SimpleNamespace(
                    name="search_products",
                    arguments='{"query": "colchon"}',
                ),
            )
            message = SimpleNamespace(content="", tool_calls=[call])
        else:
            message = SimpleNamespace(content=self.final_text or "", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _agent_with(completions: _FakeCompletions) -> Agent:
    agent = Agent()
    agent._llm = lambda: SimpleNamespace(chat=SimpleNamespace(completions=completions))  # type: ignore[method-assign]
    return agent


async def test_cierra_respuesta_tras_agotar_herramientas(session):
    contact = Contact(wa_id="59170000999", phone_e164="+59170000999", name="Ana")
    session.add(contact)
    await session.commit()

    completions = _FakeCompletions("No hay colchones en promoción, pero sí hay stock.")
    reply = await _agent_with(completions).handle(
        session, contact, "Tienes colchones en promoción?"
    )

    assert completions.calls == 5  # 4 turnos con herramientas + cierre
    assert "promoción" in reply.messages[0].text
    assert "No pude completar" not in reply.messages[0].text


async def test_sin_cierre_del_llm_usa_modo_demo(session):
    contact = Contact(wa_id="59170000998", phone_e164="+59170000998", name="Ana")
    session.add(contact)
    await session.commit()

    completions = _FakeCompletions(None)  # el cierre viene vacío
    reply = await _agent_with(completions).handle(
        session, contact, "Tienes colchones en promoción?"
    )

    text = reply.messages[0].text
    assert text.strip()
    assert "No pude completar" not in text
