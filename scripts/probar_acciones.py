"""Prueba de acciones: los botones responden aunque se repitan.

Recorre un carrito completo con un contacto temporal y verifica que ninguna
acción quede tapada por los guards. Borra todo al terminar.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete, select

from app.agent import Agent
from app.db import SessionLocal
from app.models import (
    Cart,
    CartItem,
    Contact,
    Conversation,
    ConversationFlow,
    ConversationGuard,
    ConversationState,
    Handoff,
    Message,
)
from app.services import catalog


async def main() -> int:
    async with SessionLocal() as session:
        productos = await catalog.search_items(session, "taladro", limit=3)
        if not productos:
            print("sin productos para probar")
            return 1
        sku = productos[0].sku

        sufijo = uuid.uuid4().hex[:8]
        contacto = Contact(
            wa_id=f"prueba{sufijo}", phone_e164=f"+0{sufijo}", name="Prueba"
        )
        session.add(contacto)
        await session.flush()
        conversation = Conversation(contact_id=contacto.id)
        session.add(conversation)
        await session.commit()

        pasos = [
            ("product:" + sku, "ficha"),
            ("product:" + sku, "ficha repetida"),
            ("add:" + sku + ":1", "agregar"),
            ("cart", "carrito"),
            ("qty:" + sku + ":2", "cantidad"),
            ("cart", "carrito otra vez"),
            ("more", "ver más"),
            ("catalog", "catálogo"),
        ]
        fallos = 0
        for mensaje, etiqueta in pasos:
            agente = Agent()
            try:
                respuesta = await agente.handle(session, contacto, mensaje)
                respuesta = await agente.postprocess(
                    session, contacto, mensaje, respuesta
                )
            except Exception as exc:  # noqa: BLE001
                print(f"FALLA {etiqueta}: {type(exc).__name__} {exc}")
                fallos += 1
                continue
            texto = " ".join(m.text or "" for m in respuesta.messages)
            tapada = "ya te mostré" in texto.lower()
            vacia = not texto.strip()
            estado = "FALLA" if (tapada or vacia) else "OK   "
            if estado == "FALLA":
                fallos += 1
            print(f"[{estado}] {etiqueta}: {texto[:90].replace(chr(10), ' ')}")

        # Limpieza: nada de esto debe quedar en la base.
        conversaciones = (
            await session.scalars(
                select(Conversation.id).where(
                    Conversation.contact_id == contacto.id
                )
            )
        ).all()
        for tabla in (
            Message,
            Handoff,
            ConversationFlow,
            ConversationState,
            ConversationGuard,
        ):
            if conversaciones:
                await session.execute(
                    delete(tabla).where(
                        tabla.conversation_id.in_(conversaciones)
                    )
                )
        carritos = (
            await session.scalars(
                select(Cart.id).where(Cart.contact_id == contacto.id)
            )
        ).all()
        for carrito in carritos:
            await session.execute(
                delete(CartItem).where(CartItem.cart_id == carrito)
            )
        await session.execute(delete(Cart).where(Cart.contact_id == contacto.id))
        await session.execute(
            delete(Conversation).where(Conversation.contact_id == contacto.id)
        )
        await session.execute(delete(Contact).where(Contact.id == contacto.id))
        await session.commit()

        print(f"\nacciones: {len(pasos)} | fallos: {fallos}")
        return 0 if fallos == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
