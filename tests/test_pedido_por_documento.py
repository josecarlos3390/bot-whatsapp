"""Seguimiento por CI/NIT cuando no hay número de pedido."""

from __future__ import annotations

from app.services import order_by_document


def test_detecta_el_documento():
    assert order_by_document.extract_documento("mi carnet es 500195") == "500195"
    assert order_by_document.extract_documento("NIT 123456789") == "123456789"
    assert order_by_document.extract_documento("500195") == "500195"


def test_no_confunde_el_id_de_pedido_con_documento():
    assert (
        order_by_document.extract_documento("1670220500193-01") is None
    )
    assert (
        order_by_document.extract_documento("mi pedido 1672200500195") is None
    )


def test_sin_numero_no_hay_documento():
    assert order_by_document.extract_documento("no me acuerdo") is None
    assert order_by_document.extract_documento("") is None


async def test_sin_compras_ofrece_asesor(session, monkeypatch):
    from app.models import Contact
    from app.services import order_by_document as modulo

    contacto = Contact(wa_id="59170027001", phone_e164="+59170027001")
    session.add(contacto)
    await session.commit()

    class SapFalso:
        async def get_customer_purchases(self, term, top=5, skip=0):
            return []

    monkeypatch.setattr(
        "app.sap.get_sap", lambda session: SapFalso(), raising=True
    )

    resultado = await modulo.lookup_by_document(session, contacto, "500195")

    assert resultado["needs_handoff"] is True
    assert "asesor" in resultado["text"].lower()
    assert contacto.tax_id == "500195"


async def test_con_una_compra_muestra_el_pedido(session, monkeypatch):
    from app.models import Contact
    from app.services import order_by_document as modulo

    contacto = Contact(wa_id="59170027002", phone_e164="+59170027002")
    session.add(contacto)
    await session.commit()

    pedido = {
        "orderId": "1672200500195-01",
        "status": "ready-for-handling",
        "value": 220,
        "creationDate": "2026-10-20T10:00:00Z",
        "items": [{"name": "Set de brocas", "quantity": 1, "price": 220}],
    }

    class SapFalso:
        async def get_customer_purchases(self, term, top=5, skip=0):
            return [pedido]

    monkeypatch.setattr(
        "app.sap.get_sap", lambda session: SapFalso(), raising=True
    )

    resultado = await modulo.lookup_by_document(session, contacto, "500195")

    assert "1672200500195-01" in resultado["text"]
    assert resultado["needs_handoff"] is False
