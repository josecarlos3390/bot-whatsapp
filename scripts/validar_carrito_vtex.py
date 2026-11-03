"""Validación de punta a punta del carrito de VTEX (vía PaaS).

Se corre **cuando el PaaS publique las rutas**. Antes no tiene sentido: no
existen en el puerto 5050.

Uso:
    python -m scripts.validar_carrito_vtex            # solo consulta
    python -m scripts.validar_carrito_vtex --crear    # crea un carrito de prueba
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Cart, CartItem, CatalogItem, Contact
from app.services import vtex_cart


def _ok(texto: str) -> None:
    print(f"  ✓ {texto}")


def _mal(texto: str) -> None:
    print(f"  ✗ {texto}")


async def _sku_de_prueba(session) -> CatalogItem | None:
    return await session.scalar(
        select(CatalogItem)
        .where(CatalogItem.active.is_(True), CatalogItem.stock > 2)
        .limit(1)
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crear", action="store_true")
    args = parser.parse_args()

    print("1. Configuración")
    print(f"  · VTEX_CART_ENABLED = {settings.vtex_cart_enabled}")
    print(f"  · VTEX_CART_VIA     = {settings.vtex_cart_via}")
    print(f"  · PaaS              = {settings.sap_paas_url or '(vacío)'}")
    print(f"  · seller            = {settings.vtex_seller_id}")
    print(f"  · sales channel     = {settings.vtex_sales_channel}")
    if not vtex_cart.disponible():
        _mal("el carrito no está configurado (falta llave o bandera)")
        return 1
    if not settings.vtex_cart_enabled:
        _mal("la bandera está apagada: activala solo para esta prueba")
        return 1

    async with SessionLocal() as session:
        articulo = await _sku_de_prueba(session)
        if articulo is None:
            _mal("no hay productos para probar")
            return 1
        print(f"\n2. Producto de prueba: {articulo.sku} · {articulo.name[:40]}")

        contacto = Contact(
            wa_id=f"prueba-{uuid.uuid4().hex[:8]}",
            phone_e164="+59170000000",
            name="Prueba VTEX",
        )
        session.add(contacto)
        await session.flush()
        carrito = Cart(contact_id=contacto.id, status="active")
        session.add(carrito)
        await session.flush()
        session.add(
            CartItem(
                cart_id=carrito.id,
                sku=articulo.sku,
                quantity=1,
                unit_price=Decimal(str(articulo.price or 0)),
                list_price=Decimal(str(articulo.price or 0)),
            )
        )
        await session.commit()
        await session.refresh(carrito, attribute_names=["items"])

        print("\n3. Crear carrito")
        try:
            creado = await vtex_cart.crear_carrito(carrito)
        except Exception as exc:  # noqa: BLE001
            _mal(f"no se pudo crear: {str(exc)[:120]}")
            print("\n  (¿están publicadas las rutas en el PaaS?)")
            return 1
        carrito.vtex_order_form_id = creado["order_form_id"]
        carrito.vtex_cart_url = creado["checkout_url"] or ""
        _ok(f"order_form_id = {creado['order_form_id'][:8]}…")
        _ok(f"checkout_url  = {creado['checkout_url'] or 'null (no se muestra link)'}")
        _ok(f"expires_at    = {creado.get('expires_at') or 'null (TTL 24 h del bot)'}")

        print("\n4. Agregar ítem")
        try:
            respuesta = await vtex_cart.agregar_items(
                carrito,
                [{"sku": articulo.sku, "quantity": 1}],
            )
        except Exception as exc:  # noqa: BLE001
            _mal(f"no se pudo agregar: {str(exc)[:120]}")
            return 1
        if respuesta["items"]:
            _ok(
                f"quedó {respuesta['items'][0]['quantity']} × "
                f"{respuesta['items'][0]['sku']} a Bs {respuesta['items'][0]['price']}"
            )
        else:
            _mal("el ítem no quedó en el carrito")
        if respuesta["messages"]:
            for mensaje in respuesta["messages"]:
                _mal(f"rechazo {mensaje['code']}: {mensaje['text'][:80]}")
        _ok(f"total VTEX = {respuesta['value']} {respuesta['currency']}")

        print("\n5. Consultar carrito")
        actual = await vtex_cart.consultar(carrito)
        if actual is None:
            _mal("el carrito no se pudo consultar")
        else:
            _ok(f"consulta ok · {len(actual['items'])} ítem(s)")
            _ok(f"vigente = {await vtex_cart.asegurar_vigente(carrito)}")

        print("\n6. Sincronización completa del carrito local")
        resultado = await vtex_cart.sincronizar(carrito)
        _ok(f"estado = {resultado['estado']}")
        if resultado["link"]:
            _ok(f"link para el cliente = {resultado['link']}")
        else:
            _ok("sin link: el bot no lo muestra (correcto si checkout_url es null)")

        print("\n7. Limpieza")
        await session.delete(carrito)
        await session.delete(contacto)
        await session.commit()
        _ok("datos de prueba borrados")

    print("\nValidación terminada.")
    if not settings.vtex_cart_enabled:
        print("Recordá dejar VTEX_CART_ENABLED=false al terminar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
