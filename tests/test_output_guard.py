"""Validación de salida: la respuesta final no puede contradecir la política."""

from __future__ import annotations

from app.agent import AgentReply, Outbound
from app.models import CatalogItem, Contact
from app.services import output_guard


def _reply(messages: list[Outbound]) -> AgentReply:
    return AgentReply(messages)


async def test_tema_sensible_reemplaza_productos_por_empatia(session):
    contact = Contact(wa_id="59170000871", phone_e164="+59170000871")
    session.add(contact)
    await session.commit()

    reply = _reply(
        [
            Outbound(
                kind="image",
                url="https://cdn.example.com/sombrilla.png",
                text="Sombrilla parasol",
            ),
            Outbound(
                kind="list",
                text="Mirá esto",
                sections=[
                    {
                        "title": "Opciones",
                        "rows": [
                            {
                                "id": "product:SOMB-1",
                                "title": "Sombrilla",
                                "description": "Bs 2.549",
                            }
                        ],
                    }
                ],
            ),
        ]
    )

    result = await output_guard.sanitize(
        session, reply, "Murió mi mascota, por eso estoy triste"
    )

    texto = " ".join(m.text or "" for m in result.messages)
    assert "lamento" in texto.lower()
    assert all(m.kind != "image" for m in result.messages)
    assert not any(
        str(row.get("id", "")).startswith("product:")
        for message in result.messages
        for section in (message.sections or [])
        for row in section.get("rows") or []
    )


async def test_frase_prohibida_se_reemplaza(session):
    reply = _reply(
        [Outbound(text="No tengo una sección específica de vacaciones.")]
    )

    result = await output_guard.sanitize(session, reply, "busco algo de vacaciones")

    texto = " ".join(m.text or "" for m in result.messages)
    assert "sección específica" not in texto.lower()
    assert "categoría armada" in texto.lower()


async def test_quita_sku_inexistente_y_conserva_el_real(session):
    session.add(
        CatalogItem(
            sku="REAL-1",
            name="COLCHON REAL",
            price=1000,
            stock=2,
            active=True,
        )
    )
    await session.commit()

    reply = _reply(
        [
            Outbound(
                kind="list",
                text="Opciones",
                sections=[
                    {
                        "title": "Opciones",
                        "rows": [
                            {"id": "product:REAL-1", "title": "Real"},
                            {"id": "product:NOEXISTE-9", "title": "Fantasma"},
                        ],
                    }
                ],
            )
        ]
    )

    result = await output_guard.sanitize(session, reply, "busco colchon")

    rows = result.messages[0].sections[0]["rows"]
    assert [row["id"] for row in rows] == ["product:REAL-1"]


async def test_respuesta_normal_no_se_toca(session):
    reply = _reply([Outbound(text="Tenemos colchones desde Bs 1.190.")])

    result = await output_guard.sanitize(session, reply, "cuanto sale un colchon")

    assert result.messages[0].text == "Tenemos colchones desde Bs 1.190."
