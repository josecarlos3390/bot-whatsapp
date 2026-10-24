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


async def test_corrige_precio_inventado_en_la_ficha(session):
    session.add(
        CatalogItem(
            sku="PRECIO-1",
            name="COLCHON PRECIO",
            price=1190,
            stock=3,
            active=True,
        )
    )
    await session.commit()

    reply = _reply(
        [
            Outbound(
                kind="list",
                text="Colchón Eco Flex\nPrecio: Bs 9.999,00",
                sections=[
                    {
                        "title": "Acciones",
                        "rows": [
                            {"id": "add:PRECIO-1:1", "title": "Agregar 1"}
                        ],
                    }
                ],
            )
        ]
    )

    result = await output_guard.sanitize(session, reply, "product:PRECIO-1")

    texto = result.messages[0].text
    assert "9.999" not in texto
    assert "1,190.00" in texto


async def test_precio_correcto_no_se_toca(session):
    session.add(
        CatalogItem(
            sku="PRECIO-2",
            name="COLCHON PRECIO",
            price=1190,
            stock=3,
            active=True,
        )
    )
    await session.commit()

    reply = _reply(
        [
            Outbound(
                kind="list",
                text="Colchón Eco Flex\nPrecio: Bs 1,190.00",
                sections=[
                    {
                        "title": "Acciones",
                        "rows": [
                            {"id": "add:PRECIO-2:1", "title": "Agregar 1"}
                        ],
                    }
                ],
            )
        ]
    )

    result = await output_guard.sanitize(session, reply, "product:PRECIO-2")

    assert "1,190.00" in result.messages[0].text


async def test_total_del_carrito_no_se_toca(session):
    session.add(
        CatalogItem(
            sku="PRECIO-3",
            name="COLCHON PRECIO",
            price=1190,
            stock=3,
            active=True,
        )
    )
    await session.commit()

    reply = _reply(
        [
            Outbound(
                kind="buttons",
                text="Tu carrito va en *Bs 3,380.00*.",
                buttons=[{"id": "add:PRECIO-3:2", "title": "Agregar"}],
            )
        ]
    )

    result = await output_guard.sanitize(session, reply, "add:PRECIO-3:2")

    assert "3,380.00" in result.messages[0].text