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


def test_detecta_el_tipo_de_numero_en_el_texto():
    assert order_by_document.tipo_del_texto("mi carnet es 500195") == "carnet"
    assert order_by_document.tipo_del_texto("el NIT 123456789") == "nit"
    assert order_by_document.tipo_del_texto("mi celular 72100717") == "telefono"
    assert order_by_document.tipo_del_texto("500195") is None


def test_la_pregunta_ofrece_los_tres_tipos():
    pregunta = order_by_document.pregunta_tipo("500195")

    assert "500195" in pregunta["text"]
    assert [b["id"] for b in pregunta["buttons"]] == [
        "doc:carnet",
        "doc:nit",
        "doc:telefono",
    ]
    assert pregunta["finished"] is False


async def test_busqueda_por_telefono_usa_el_documento(session, monkeypatch):
    from app.models import Contact
    from app.services import order_by_document as modulo

    contacto = Contact(wa_id="59170027003", phone_e164="+59170027003")
    session.add(contacto)
    await session.commit()

    class SapFalso:
        llamadas: list[str] = []

        async def get_customer_purchases(self, term, top=5, skip=0):
            self.llamadas.append(term)
            if term == "72100717":
                return []
            return [{"orderId": "1672200500195-01", "status": "invoiced", "value": 100}]

        async def get_customer(self, term):
            return {"document": "500195"}

        async def get_order(self, numero):
            return {
                "orderId": numero,
                "status": "invoiced",
                "value": 100,
                "items": [],
            }

    monkeypatch.setattr(
        "app.sap.get_sap", lambda session: SapFalso(), raising=True
    )

    resultado = await modulo.lookup_by_document(
        session, contacto, "72100717", "telefono"
    )

    assert "1672200500195-01" in resultado["text"]
    assert resultado["needs_handoff"] is False