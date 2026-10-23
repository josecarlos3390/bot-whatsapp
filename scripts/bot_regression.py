"""Regresión rápida del bot conversacional.

Uso:
    python scripts/bot_regression.py           # pruebas offline
    python scripts/bot_regression.py --live    # además prueba diálogos con DeepSeek

Las pruebas live consumen API y requieren .env/configuración de la base.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agent import Agent, _clean_query, _requested_size  # noqa: E402
from app.db import Base, SessionLocal  # noqa: E402
from app.models import Contact, Conversation, ConversationState  # noqa: E402
from app.services import conversation_state  # noqa: E402


SCENARIOS = [
    ("Tienes televisores", ["televisor"]),
    ("50 pulgadas", ["50"]),
    ("Tienes heladeras", ["heladera"]),
    ("Samsung", ["samsung", "refrig", "refrigerador"]),
    ("Tienes lavadoras", ["lavadora"]),
    ("LG", ["lg", "lavadora"]),
    ("busco aires acondicionados", ["aire", "equipo", "climatiz"]),
    ("Busco air acondicionados", ["aire", "aire acondicionado"]),
    ("Busco colchones de 2 plazas", ["colchon", "2 plaza"]),
    ("Muéstrame colchones queen", ["colchon", "queen"]),
    ("Tienes televisor de 55 pulgadas", ["55"]),
    ("Tienes un televisor Sony", ["sony", "televisor"]),
    ("Busco refrigerador", ["refri", "refrigerador", "heladera"]),
    ("Nevera pequeña", ["nevera", "refri", "heladera"]),
    ("Busco microondas", ["microondas"]),
    ("Tienes licuadora", ["licuadora"]),
    ("Precio del televisor", ["precio", "televisor"]),
    ("Quiero ver mis compras", ["ci", "nit", "carnet"]),
    ("¿Qué compré?", ["ci", "nit", "carnet"]),
    ("Hola", ["rohi"]),
    ("Quiero un asesor", ["avisé", "derivé", "equipo"]),
    ("Tienes algo para la sala", ["sala", "mueble"]),
    ("Busco pintura blanca", ["pintura"]),
    ("Tienes taladro", ["taladro"]),
    ("Busco una cama", ["cama"]),
    ("Necesito un sofá", ["sofá", "sofa", "sillón", "sillon"]),
    ("Busco lámpara", ["lámpara", "lampara"]),
    ("TV de 65 pulgadas", ["65"]),
    ("Tienes heladera Samsung", ["samsung", "refri", "heladera"]),
    ("Busco aire acondicionado portátil", ["aire", "portatil", "portátil"]),
    ("Tienes ventiladores", ["ventilador"]),
    ("Tienes freidoras de aire", ["freidora", "aire"]),
    ("Tienes ollas", ["olla"]),
    ("Tienes juegos de sábanas", ["sábana", "sabana", "juego"]),
    ("Tienes cortinas", ["cortina"]),
    ("Tienes alfombras", ["alfombra"]),
    ("Tienes espejos", ["espejo"]),
    ("Tienes parrillas", ["parrilla"]),
    ("Tienes muebles de jardín", ["jardín", "jardin", "mueble"]),
    ("Tienes cemento", ["cemento"]),
    ("Tienes cerámicas", ["cerámica", "ceramica"]),
    ("Tienes grifería", ["grifer"]),
    ("Tienes inodoros", ["inodoro", "sanitario"]),
    ("Tienes duchas", ["ducha"]),
    ("Tienes aires de 12000 BTU", ["12000", "aire"]),
    ("Tienes lavadora Samsung", ["lavadora", "samsung"]),
    ("Tienes refrigerador LG", ["refri", "lg"]),
    ("Tienes TV de 65 pulgadas", ["65"]),
    ("Tienes colchón de 2 plazas", ["colchon", "2 plaza"]),
    ("Tienes un sofá cama", ["sofá", "sofa", "cama"]),
    ("Me llegó un producto roto", ["lamento", "disculpa", "asesor", "equipo"]),
    ("Quiero devolver un producto", ["devol", "cambio", "asesor", "equipo"]),
    ("Puedo pagar con QR", ["qr", "pago", "pagar"]),
    ("Mi pedido llegó roto, quiero devolución", ["lamento", "devol", "asesor", "equipo"]),
    ("Quiero cambiar un producto", ["cambio", "devol", "asesor", "equipo"]),
    ("Aceptan tarjeta", ["pago", "tarjeta", "asesor"]),
]


def offline() -> None:
    assert _clean_query("busco aires acondicionados") == "aires acondicionados"
    assert _clean_query("quiero comprar un televisor") == "televisor"
    assert _requested_size("50 pulgadas") == "50"
    assert _requested_size('TV de 65"') == "65"

    cards = Agent._search_cards(
        [
            {
                "sku": "TV50",
                "name": "TV 50 PULGADAS",
                "price": "100",
                "brand": "LG",
                "category": "TV",
                "description": "Televisor",
                "image_url": "",
            }
        ]
    )
    text = "\n".join(message.text for message in cards)
    assert "stock" not in text.lower()
    assert "Precio:" in text
    assert "Marca:" in text
    assert "Descripción:" in text
    print("offline: OK")


async def state_test() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        contact = Contact(wa_id="test", phone_e164="+59100000000")
        session.add(contact)
        await session.flush()
        conversation = Conversation(contact_id=contact.id)
        session.add(conversation)
        await session.flush()

        await conversation_state.update_state(
            session,
            conversation.id,
            category="heladera",
            brand="Samsung",
            size="50",
        )
        row = await conversation_state.get_state(session, conversation.id)
        assert row.category == "heladera"
        assert row.brand == "Samsung"
        assert row.size == "50"

        await conversation_state.update_state(
            session,
            conversation.id,
            category="televisor",
        )
        row = await conversation_state.get_state(session, conversation.id)
        assert row.category == "televisor"
        assert row.brand is None
        assert row.size is None
    await engine.dispose()
    print("state: OK")


async def live() -> None:
    async with SessionLocal() as session:
        contact = await session.scalar(
            select(Contact)
            .where(
                Contact.tax_id.is_(None),
                Contact.sap_card_code.is_(None),
            )
            .limit(1)
        )
        if contact is None:
            contact = await session.scalar(select(Contact).limit(1))
        if contact is None:
            raise SystemExit("No hay contactos en la base para probar")

        failures = 0
        for message, expected in SCENARIOS:
            reply = await Agent().handle(session, contact, message, [], None)
            text = " ".join(item.text or "" for item in reply.messages)
            lower = text.lower()
            ok = any(term.lower() in lower for term in expected)
            if "no tengo busco" in lower or "en stock" in lower:
                ok = False
            print(
                ("OK  " if ok else "FAIL"),
                message,
                "->",
                text[:170].replace("\n", " | "),
            )
            failures += 0 if ok else 1

        context_steps = [
            ("Tienes televisores", ["televisor"]),
            ("Ahora quiero heladeras", ["heladera"]),
            ("Samsung", ["samsung", "refrig", "refrigerador"]),
            ("Tienes lavadoras", ["lavadora"]),
            ("Ahora quiero televisores", ["televisor"]),
            ("50 pulgadas", ["50"]),
            ("Tienes televisores", ["televisor"]),
            ("Ahora quiero colchones", ["colchon"]),
            ("2 plazas", ["2 plaza"]),
        ]
        for message, expected in context_steps:
            reply = await Agent().handle(session, contact, message, [], None)
            text = " ".join(item.text or "" for item in reply.messages)
            lower = text.lower()
            ok = any(term.lower() in lower for term in expected)
            if "no tengo busco" in lower or "en stock" in lower:
                ok = False
            print(
                ("OK  " if ok else "FAIL"),
                "CONTEXTO:",
                message,
                "->",
                text[:170].replace("\n", " | "),
            )
            failures += 0 if ok else 1

        if failures:
            raise SystemExit(
                f"{failures} de {len(SCENARIOS) + len(context_steps)} "
                "escenarios fallaron"
            )
        print(
            f"live: OK ({len(SCENARIOS)} escenarios + "
            f"{len(context_steps)} de contexto)"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    offline()
    asyncio.run(state_test())
    if args.live:
        asyncio.run(live())


if __name__ == "__main__":
    main()
