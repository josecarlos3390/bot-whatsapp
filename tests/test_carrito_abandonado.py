"""Recordatorio de carrito sin terminar."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from decimal import Decimal

from app.models import (
    Cart,
    CartItem,
    CartReminder,
    CatalogItem,
    Contact,
    Conversation,
    Message,
)
from app.services import carrito_abandonado


async def _contacto(session, wa_id="59170040001", nombre="JoseKa"):
    contacto = Contact(wa_id=wa_id, phone_e164=f"+{wa_id}", name=nombre)
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()
    return contacto


async def _carrito(session, contacto, hace_horas=5):
    carrito = Cart(contact_id=contacto.id, status="active")
    session.add(carrito)
    await session.flush()
    session.add(
        CartItem(
            cart_id=carrito.id,
            sku="REM-001",
            quantity=2,
            unit_price=Decimal("1000"),
            list_price=Decimal("1000"),
        )
    )
    session.add(
        CatalogItem(
            sku="REM-001",
            name="Impermeabilizante de prueba",
            price="1000",
            stock=5,
            category="Pintura",
            active=True,
        )
    )
    carrito.updated_at = datetime.now(timezone.utc) - timedelta(
        hours=hace_horas
    )
    await session.commit()
    return carrito


async def test_detecta_el_carrito_quieto(session):
    contacto = await _contacto(session)
    await _carrito(session, contacto, hace_horas=5)

    pendientes = await carrito_abandonado.pendientes(session, horas=3)

    assert len(pendientes) == 1
    carrito, quien, items = pendientes[0]
    assert quien.wa_id == contacto.wa_id
    assert items[0].sku == "REM-001"


async def test_un_carrito_recien_usado_no_entra(session):
    contacto = await _contacto(session, "59170040002")
    await _carrito(session, contacto, hace_horas=0)

    assert await carrito_abandonado.pendientes(session, horas=3) == []


async def test_si_el_bot_esta_pausado_no_recuerda(session):
    contacto = await _contacto(session, "59170040003")
    await _carrito(session, contacto, hace_horas=6)
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contacto.id)
    )
    conversacion.bot_paused = True
    await session.commit()

    assert await carrito_abandonado.pendientes(session, horas=3) == []


async def test_el_texto_lleva_productos_y_total(session):
    contacto = await _contacto(session, "59170040004")
    carrito = await _carrito(session, contacto, hace_horas=4)
    items = (
        await session.scalars(
            select(CartItem).where(CartItem.cart_id == carrito.id)
        )
    ).all()
    filas = await carrito_abandonado.enriquecer(session, items)
    total = sum(
        (fila["unit_price"] * fila["quantity"] for fila in filas),
        Decimal("0"),
    )

    texto = carrito_abandonado.texto_con_nombres(contacto, filas, total)

    assert "JoseKa" in texto
    assert "Impermeabilizante de prueba" in texto
    assert "2.000" in texto
    assert "retomar carrito" in texto


async def test_un_nombre_raro_no_ensucia_el_saludo(session):
    contacto = await _contacto(session, "59170040005", nombre=".")
    carrito = await _carrito(session, contacto, hace_horas=4)
    items = (
        await session.scalars(
            select(CartItem).where(CartItem.cart_id == carrito.id)
        )
    ).all()
    filas = await carrito_abandonado.enriquecer(session, items)
    texto = carrito_abandonado.texto_con_nombres(
        contacto, filas, Decimal("1000")
    )

    assert texto.startswith("Hola 👋")
    assert "Hola ." not in texto


async def test_un_carrito_vacio_no_se_recuerda(session):
    contacto = await _contacto(session, "59170040006")
    carrito = Cart(contact_id=contacto.id, status="active")
    session.add(carrito)
    await session.flush()
    carrito.updated_at = datetime.now(timezone.utc) - timedelta(hours=6)
    await session.commit()

    assert await carrito_abandonado.pendientes(session, horas=3) == []


async def test_no_repite_el_recordatorio(session):
    contacto = await _contacto(session, "59170040007")
    carrito = await _carrito(session, contacto, hace_horas=6)
    session.add(
        CartReminder(cart_id=carrito.id, contact_id=contacto.id, channel="text")
    )
    await session.commit()

    assert await carrito_abandonado.pendientes(session, horas=3) == []


async def test_la_ventana_se_cierra_a_las_24_horas(session):
    contacto = await _contacto(session, "59170040008")
    conversacion = await session.scalar(
        select(Conversation).where(Conversation.contact_id == contacto.id)
    )
    session.add(
        Message(
            conversation_id=conversacion.id,
            direction="in",
            type="text",
            text="hola",
            created_at=datetime.now(timezone.utc) - timedelta(hours=30),
        )
    )
    await session.commit()

    assert not await carrito_abandonado.ventana_abierta(session, contacto)
