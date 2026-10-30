"""El LLM no debe dejar al cliente sin respuesta cuando insiste con herramientas."""

from __future__ import annotations

from types import SimpleNamespace

from app.agent import Agent
from app.models import Contact


class _FakeCompletions:
    """Devuelve tool_calls las primeras veces y un cierre en la última."""

    def __init__(
        self, final_text: str | None, rounds: int = 4, tool: str = "search_products"
    ) -> None:
        self.final_text = final_text
        self.rounds = rounds
        self.tool = tool
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.rounds:
            call = SimpleNamespace(
                id=f"call_{self.calls}",
                type="function",
                function=SimpleNamespace(
                    name=self.tool,
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

    completions = _FakeCompletions(
        "No hay colchones en promoción, pero sí hay stock.",
        tool="list_promotions",
    )
    reply = await _agent_with(completions).handle(
        session, contact, "Tienes colchones de 2 plazas en promoción?"
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


async def test_busqueda_se_responde_sin_segunda_llamada(session):
    """search_products se contesta con las reglas: una sola llamada."""
    contact = Contact(wa_id="59170000997", phone_e164="+59170000997", name="Ana")
    session.add(contact)
    await session.commit()

    completions = _FakeCompletions("No debería usarse", rounds=4)
    reply = await _agent_with(completions).handle(
        session, contact, "Tienes colchones de 2 plazas?"
    )

    # La búsqueda no debe disparar el bucle completo (4 rondas).
    assert completions.calls <= 2
    assert reply.messages

async def test_no_hay_transaccion_abierta_al_llamar_al_modelo(session):
    """Con varios clientes, dejar la base bloqueada durante la IA encola."""
    from types import SimpleNamespace

    from app.agent import Agent
    from app.models import Contact

    contacto = Contact(wa_id="59170110001", phone_e164="+59170110001")
    session.add(contacto)
    await session.commit()

    abiertas: list[bool] = []

    class _Espia:
        def __init__(self):
            self.llamadas = 0

        async def create(self, **kwargs):
            abiertas.append(session.in_transaction())
            self.llamadas += 1
            mensaje = SimpleNamespace(
                content="Listo, te paso las opciones.", tool_calls=None
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=mensaje)],
                usage=None,
            )

    espia = _Espia()
    agente = Agent()
    agente._llm = lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=espia)
    )

    await agente.handle(session, contacto, "busco un taladro")

    assert abiertas, "el modelo debería haberse llamado"
    assert all(estado is False for estado in abiertas)