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
        if creado["items"]:
            _mal(
                f"el carrito nuevo ya traía {len(creado['items'])} ítem(s): "
                + ", ".join(i["sku"] for i in creado["items"])
            )

        # Dos carritos seguidos tienen que ser distintos: si el integrador
        # reutiliza el orderForm, todos los clientes comparten el carrito.
        print("\n3b. Aislamiento entre carritos")
        try:
            segundo = await vtex_cart.crear_carrito(carrito)
        except Exception as exc:  # noqa: BLE001
            _mal(f"no se pudo crear el segundo: {str(exc)[:120]}")
            return 1
        if segundo["order_form_id"] == creado["order_form_id"]:
            _mal("dos creaciones devolvieron el MISMO order_form_id")
        else:
            _ok(
                f"segundo carrito distinto ({segundo['order_form_id'][:8]}…)"
            )
        if segundo["items"]:
            _mal(
                f"el segundo carrito traía {len(segundo['items'])} ítem(s) ajenos"
            )
        else:
            _ok("el segundo carrito arranca vacío")

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
        pedidos = {articulo.sku}
        ajenos = [
            mensaje
            for mensaje in respuesta["messages"]
            if not any(sku in mensaje["text"] for sku in pedidos)
        ]
        for mensaje in ajenos:
            _mal(
                f"mensaje de otro SKU ({mensaje['code']}): "
                f"{mensaje['text'][:70]}"
            )
        propios = [
            mensaje
            for mensaje in respuesta["messages"]
            if mensaje not in ajenos
        ]
        for mensaje in propios:
            _ok(f"rechazo esperado {mensaje['code']}: {mensaje['text'][:60]}")
        if not ajenos:
            _ok(f"messages corresponde a esta request ({len(propios)})")
        _ok(f"total VTEX = {respuesta['value']} {respuesta['currency']}")

        print("\n4b. Varios productos y cantidades")
        otros = (
            await session.scalars(
                select(CatalogItem)
                .where(
                    CatalogItem.active.is_(True),
                    CatalogItem.stock > 3,
                    CatalogItem.sku != articulo.sku,
                )
                .limit(2)
            )
        ).all()
        lote = [
            {"sku": articulo.sku, "quantity": 2},
            *[{"sku": otro.sku, "quantity": 3} for otro in otros],
        ]
        try:
            varios = await vtex_cart.agregar_items(carrito, lote)
        except Exception as exc:  # noqa: BLE001
            _mal(f"no se pudo agregar el lote: {str(exc)[:120]}")
            varios = None
        if varios is not None:
            if len(varios["items"]) == len(lote):
                _ok(f"quedaron {len(lote)} productos distintos")
            else:
                _mal(
                    f"esperaba {len(lote)} productos y quedaron "
                    f"{len(varios['items'])}"
                )
            por_sku = {i["sku"]: i["quantity"] for i in varios["items"]}
            if por_sku.get(articulo.sku) == 2:
                _ok("la cantidad se actualiza, no se suma")
            else:
                _mal(f"cantidad inesperada: {por_sku.get(articulo.sku)}")
            _ok(f"total con el lote = {varios['value']} {varios['currency']}")

        print("\n4c. SKU inexistente")
        try:
            fallo = await vtex_cart.agregar_items(
                carrito, [{"sku": "NOEXISTE-999", "quantity": 1}]
            )
        except Exception as exc:  # noqa: BLE001
            _mal(f"el SKU inválido rompió la llamada: {str(exc)[:100]}")
        else:
            if any("NOEXISTE-999" in m["text"] for m in fallo["messages"]):
                _ok("el rechazo se informa en messages")
            elif fallo["messages"]:
                _ok("hay mensajes, aunque no nombran el SKU")
            else:
                _mal("el SKU inexistente no generó ningún aviso")
            if not any(i["sku"] == "NOEXISTE-999" for i in fallo["items"]):
                _ok("no quedó en el carrito")

        print("\n5. Consultar carrito")
        actual = await vtex_cart.consultar(carrito)
        if actual is None:
            _mal("el carrito no se pudo consultar")
        else:
            _ok(f"consulta ok · {len(actual['items'])} ítem(s)")
            if actual["items"]:
                sku = str(actual["items"][0].get("sku") or "")
                if sku.isdigit():
                    _mal(
                        f"el GET devuelve el id interno ({sku}): falta el "
                        "cambio de contrato en el PaaS"
                    )
                else:
                    _ok(f"el GET devuelve el RefId ({sku})")
            if actual["order_form_id"] == carrito.vtex_order_form_id:
                _ok("es el mismo carrito que se creó")
            else:
                _mal("la consulta devolvió otro order_form_id")
            _ok(f"vigente = {await vtex_cart.asegurar_vigente(carrito)}")

        print("\n6. Sincronización completa del carrito local")
        resultado = await vtex_cart.sincronizar(carrito)
        if resultado["estado"] == "ok":
            _ok(f"estado = {resultado['estado']}")
        else:
            _mal(
                f"estado = {resultado['estado']}"
                + (f" · {resultado.get('detalle')}" if resultado.get("detalle") else "")
            )
        if resultado["link"]:
            _ok(f"link para el cliente = {resultado['link']}")
        else:
            _ok("sin link: el bot no lo muestra (correcto si checkout_url es null)")

        print("\n6c. El link del cliente")
        enlace = carrito.vtex_cart_url or ""
        if not enlace:
            _mal("no hay link (checkout_url y checkout_host vinieron null)")
        else:
            esperado = (
                f"?orderFormId={carrito.vtex_order_form_id}#/cart" in enlace
            )
            if esperado:
                _ok(f"formato correcto: {enlace[:70]}…")
            else:
                _mal(f"formato inesperado: {enlace[:80]}")
            import httpx

            host = enlace.split("/checkout/")[0]
            api = (
                f"{host}/api/checkout/pub/orderForm/"
                f"{carrito.vtex_order_form_id}"
            )
            try:
                respuesta_api = httpx.get(api, timeout=20)
                if respuesta_api.status_code == 200:
                    datos = respuesta_api.json()
                    items_api = datos.get("items") or []
                    _ok(
                        f"la API del carrito devuelve {len(items_api)} ítem(s) "
                        f"y total {datos.get('value')}"
                    )
                else:
                    _mal(f"la API del carrito respondió {respuesta_api.status_code}")
            except Exception as exc:  # noqa: BLE001
                _mal(f"no se pudo consultar la API del carrito: {str(exc)[:80]}")

        print("\n6b. Sincronizar otra vez no duplica")
        antes = len(await vtex_cart.consultar(carrito) or {"items": []})
        repetido = await vtex_cart.sincronizar(carrito)
        despues = (await vtex_cart.consultar(carrito) or {}).get("items", [])
        if len(despues) <= antes and repetido["estado"] == "ok":
            _ok(f"sigue con {len(despues)} ítem(s), sin duplicar")
        else:
            _mal(f"quedaron {len(despues)} ítem(s) (antes {antes})")

        print("\n7. Limpieza")
        # El carrito arrastra sus ítems: se borra primero y se confirma, así
        # el contacto ya no está referenciado.
        await session.delete(carrito)
        await session.commit()
        await session.delete(contacto)
        await session.commit()
        _ok("datos de prueba borrados")

    print("\nValidación terminada.")
    if not settings.vtex_cart_enabled:
        print("Recordá dejar VTEX_CART_ENABLED=false al terminar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
