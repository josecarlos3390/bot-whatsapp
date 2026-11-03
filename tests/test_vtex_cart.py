"""Carrito espejo en VTEX: contrato acordado con el equipo del PaaS."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.config import settings
from app.models import Cart, CartItem, Contact
from app.services import vtex_cart


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(settings, "vtex_cart_enabled", True)
    monkeypatch.setattr(settings, "vtex_cart_via", "paas")
    monkeypatch.setattr(settings, "sap_paas_url", "http://paas.local")
    monkeypatch.setattr(settings, "sap_paas_api_key", "llave")
    monkeypatch.setattr(settings, "sap_paas_tenant", "RETAIL_QA5")
    monkeypatch.setattr(settings, "vtex_sales_channel", 1)
    monkeypatch.setattr(settings, "vtex_affiliate_id", "")
    monkeypatch.setattr(settings, "vtex_checkout_host", "")


async def _carrito(session, skus=("REF-1",)) -> Cart:
    contacto = Contact(
        wa_id="59170060001", phone_e164="+59170060001", name="Ana"
    )
    session.add(contacto)
    await session.flush()
    carrito = Cart(contact_id=contacto.id, status="active")
    session.add(carrito)
    await session.flush()
    for sku in skus:
        session.add(
            CartItem(
                cart_id=carrito.id,
                sku=sku,
                quantity=2,
                unit_price=Decimal("100"),
                list_price=Decimal("100"),
            )
        )
    await session.commit()
    await session.refresh(carrito, attribute_names=["items"])
    return carrito


class FakePaaS:
    """Integrador simulado con el contrato acordado."""

    def __init__(self, checkout_url=None, rechazar=()):
        self.checkout_url = checkout_url
        self.rechazar = set(rechazar)
        self.creados = 0
        self.agregados: list[dict] = []
        self.consultas = 0
        self.vivo = True

    async def pedir(self, metodo, ruta, *, cart=None, json_body=None):
        if metodo == "POST" and ruta == "/api/vtex/cart":
            self.creados += 1
            return {
                "order_form_id": "OF-1",
                "orderFormId": "OF-1",
                "checkout_url": self.checkout_url,
                "items": [],
                "value": 0,
                "currency": "BOB",
            }
        if metodo == "POST" and ruta.endswith("/items"):
            self.agregados.append(json_body)
            items = [
                item
                for item in json_body["items"]
                if item["sku"] not in self.rechazar
            ]
            mensajes = [
                {
                    "code": "ORD027",
                    "text": f"Ítem {sku} no encontrado o no disponible",
                    "status": "error",
                }
                for sku in self.rechazar
            ]
            valor = sum(165.0 * item["quantity"] for item in items)
            return {
                "order_form_id": "OF-1",
                "items": [
                    {
                        "sku": item["sku"],
                        "sku_id": "5031",
                        "quantity": item["quantity"],
                        "price": 165.0,
                    }
                    for item in items
                ],
                "value": valor,
                "currency": "BOB",
                "messages": mensajes,
            }
        if metodo == "GET":
            self.consultas += 1
            if not self.vivo:
                raise vtex_cart.CarritoVencido("404")
            return {
                "order_form_id": "OF-1",
                "checkout_url": self.checkout_url,
                "items": [{"sku": "REF-1", "quantity": 2, "price": 165.0}],
                "value": 330.0,
                "currency": "BOB",
            }
        raise AssertionError(f"ruta inesperada: {metodo} {ruta}")


async def test_crear_carrito_acepta_las_dos_claves(session, monkeypatch):
    carrito = await _carrito(session)
    fake = FakePaaS()
    monkeypatch.setattr(vtex_cart, "_pedir", fake.pedir)

    creado = await vtex_cart.crear_carrito(carrito)

    assert creado["order_form_id"] == "OF-1"


def test_normalizar_acepta_orderFormId():
    assert vtex_cart.normalizar({"orderFormId": "ABC"})["order_form_id"] == "ABC"
    assert vtex_cart.normalizar({"order_form_id": "XYZ"})["order_form_id"] == "XYZ"


async def test_sin_checkout_url_no_hay_link(session, monkeypatch):
    carrito = await _carrito(session)
    fake = FakePaaS(checkout_url=None)
    monkeypatch.setattr(vtex_cart, "_pedir", fake.pedir)

    resultado = await vtex_cart.sincronizar(carrito)

    assert resultado["estado"] == "ok"
    assert resultado["link"] == ""
    assert vtex_cart.link_para_pagar(carrito) == ""


async def test_con_checkout_url_hay_link(session, monkeypatch):
    carrito = await _carrito(session)
    fake = FakePaaS(
        checkout_url="https://roho.com.bo/checkout/#/orderform/OF-1"
    )
    monkeypatch.setattr(vtex_cart, "_pedir", fake.pedir)

    resultado = await vtex_cart.sincronizar(carrito)

    assert resultado["link"].startswith("https://roho.com.bo/checkout/")


async def test_un_item_rechazado_marca_incompleto(session, monkeypatch):
    carrito = await _carrito(session, skus=("REF-1", "REF-2"))
    fake = FakePaaS(rechazar={"REF-2"})
    monkeypatch.setattr(vtex_cart, "_pedir", fake.pedir)

    resultado = await vtex_cart.sincronizar(carrito)

    assert resultado["estado"] == "incompleto"
    assert resultado["faltantes"] == ["REF-2"]
    assert any("REF-2" in m["text"] for m in resultado["mensajes"])


async def test_manda_el_refid_y_cantidad(session, monkeypatch):
    carrito = await _carrito(session, skus=("PTRPARD020198",))
    fake = FakePaaS()
    monkeypatch.setattr(vtex_cart, "_pedir", fake.pedir)

    await vtex_cart.sincronizar(carrito)

    enviado = fake.agregados[0]["items"][0]
    assert enviado["sku"] == "PTRPARD020198"
    assert enviado["quantity"] == 2
    assert enviado["seller"] == "1"


async def test_usa_la_idempotency_key(session):
    carrito = await _carrito(session)

    cabeceras = vtex_cart._cabeceras(carrito)

    assert cabeceras["Idempotency-Key"] == f"{carrito.contact_id}:{carrito.id}"


async def test_no_reutiliza_un_carrito_vencido(session, monkeypatch):
    carrito = await _carrito(session)
    fake = FakePaaS()
    monkeypatch.setattr(vtex_cart, "_pedir", fake.pedir)
    await vtex_cart.sincronizar(carrito)
    assert fake.creados == 1

    carrito.vtex_synced_at = datetime.now(timezone.utc) - timedelta(hours=25)
    await session.commit()

    await vtex_cart.sincronizar(carrito)
    assert fake.creados == 2


async def test_un_carrito_404_no_esta_vigente(session, monkeypatch):
    carrito = await _carrito(session)
    fake = FakePaaS()
    monkeypatch.setattr(vtex_cart, "_pedir", fake.pedir)
    await vtex_cart.sincronizar(carrito)

    fake.vivo = False
    carrito.vtex_synced_at = datetime.now(timezone.utc)
    await session.commit()

    assert not await vtex_cart.asegurar_vigente(carrito)


async def test_si_el_integrador_falla_el_carrito_local_sigue(
    session, monkeypatch
):
    carrito = await _carrito(session)

    async def _falla(*args, **kwargs):
        raise vtex_cart.VtexCartError("502")

    monkeypatch.setattr(vtex_cart, "_pedir", _falla)

    resultado = await vtex_cart.sincronizar(carrito)

    assert resultado["estado"] == "error"
    assert vtex_cart.link_para_pagar(carrito) == ""
    assert len(carrito.items) == 1  # el carrito local no se toca


async def test_el_precio_es_el_de_vtex(session, monkeypatch):
    carrito = await _carrito(session)
    fake = FakePaaS()
    monkeypatch.setattr(vtex_cart, "_pedir", fake.pedir)

    await vtex_cart.sincronizar(carrito)

    # 2 × 165 (precio de VTEX), no 2 × 100 (precio local).
    assert carrito.vtex_value == Decimal("330.0")
    assert carrito.vtex_currency == "BOB"

async def test_el_seller_sale_de_la_configuracion(session, monkeypatch):
    monkeypatch.setattr(settings, "vtex_seller_id", "7")
    carrito = await _carrito(session, skus=("REF-9",))
    fake = FakePaaS()
    monkeypatch.setattr(vtex_cart, "_pedir", fake.pedir)

    await vtex_cart.sincronizar(carrito)

    assert fake.agregados[0]["items"][0]["seller"] == "7"

def test_expires_at_se_lee_si_viene():
    datos = {
        "order_form_id": "OF-9",
        "expires_at": "2026-11-04T12:00:00Z",
    }

    carrito = vtex_cart.normalizar(datos)

    assert carrito["expires_at"] is not None
    assert carrito["expires_at"].year == 2026


def test_expires_at_null_usa_el_ttl_del_bot():
    carrito = vtex_cart.normalizar({"order_form_id": "OF-9"})

    assert carrito["expires_at"] is None
