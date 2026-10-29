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

        async def get_order(self, numero):
            return {
                **pedido,
                "clientProfileData": {"document": "500195"},
            }

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
                "clientProfileData": {"document": "500195"},
            }

    monkeypatch.setattr(
        "app.sap.get_sap", lambda session: SapFalso(), raising=True
    )

    resultado = await modulo.lookup_by_document(
        session, contacto, "72100717", "telefono"
    )

    assert "1672200500195-01" in resultado["text"]
    assert resultado["needs_handoff"] is False

def test_variantes_del_telefono():
    variantes = order_by_document.variantes_telefono("+591 69006969")

    assert "59169006969" in variantes
    assert "69006969" in variantes
    assert "069006969" in variantes


def test_numero_muy_corto_no_genera_variantes():
    assert order_by_document.variantes_telefono("123") == []


async def test_busca_por_el_telefono_de_la_conversacion(session, monkeypatch):
    from app.models import Contact
    from app.services import order_by_document as modulo

    contacto = Contact(
        wa_id="59170028001", phone_e164="+59169006969", name="Chipi"
    )
    session.add(contacto)
    await session.commit()

    class SapFalso:
        async def get_customer_purchases(self, term, top=5, skip=0):
            if term == "69006969":
                return [
                    {
                        "orderId": "1672200500195-01",
                        "status": "invoiced",
                        "value": 220,
                    }
                ]
            return []

        async def get_order(self, numero):
            return {
                "orderId": numero,
                "status": "invoiced",
                "value": 220,
                "items": [],
                "clientProfileData": {"document": "500195", "phone": "+59169006969"},
            }

    monkeypatch.setattr(
        "app.sap.get_sap", lambda session: SapFalso(), raising=True
    )

    resultado = await modulo.lookup_by_phone(session, contacto)

    assert resultado is not None
    assert "1672200500195-01" in resultado["text"]


async def test_sin_coincidencias_devuelve_none(session, monkeypatch):
    from app.models import Contact
    from app.services import order_by_document as modulo

    contacto = Contact(wa_id="59170028002", phone_e164="+59172100717")
    session.add(contacto)
    await session.commit()

    class SapVacio:
        async def get_customer_purchases(self, term, top=5, skip=0):
            return []

    monkeypatch.setattr(
        "app.sap.get_sap", lambda session: SapVacio(), raising=True
    )

    assert await modulo.lookup_by_phone(session, contacto) is None

async def test_con_documento_guardado_resuelve_sin_preguntar(session, monkeypatch):
    from app.models import Contact, Conversation
    from app.agent import Agent

    contacto = Contact(
        wa_id="59170029001",
        phone_e164="+59170029001",
        name="Chipi",
        tax_id="500195",
    )
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    class SapFalso:
        async def get_customer_purchases(self, term, top=5, skip=0):
            if term == "500195":
                return [{"orderId": "1672200500195-01", "status": "invoiced", "value": 220}]
            return []

        async def get_order(self, numero):
            return {
                "orderId": numero,
                "status": "invoiced",
                "value": 220,
                "items": [],
                "clientProfileData": {"document": "500195"},
            }

    monkeypatch.setattr(
        "app.sap.get_sap", lambda session: SapFalso(), raising=True
    )

    respuesta = await Agent().handle(session, contacto, "estado")
    texto = respuesta.messages[0].text or ""

    assert "1672200500195-01" in texto
    assert "Pasame el" not in texto


async def test_sin_documento_pide_los_datos(session, monkeypatch):
    from app.models import Contact, Conversation
    from app.agent import Agent

    contacto = Contact(wa_id="59170029002", phone_e164="+59170029002")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    respuesta = await Agent().handle(session, contacto, "estado")
    texto = respuesta.messages[0].text or ""

    assert "ID del pedido" in texto or "CI o NIT" in texto

def test_extrae_el_email_del_texto():
    assert (
        order_by_document.extract_email("mi correo es Ana.Perez@Gmail.com")
        == "ana.perez@gmail.com"
    )
    assert order_by_document.extract_email("no tengo correo") is None


async def test_no_muestra_un_pedido_de_otro_cliente(session, monkeypatch):
    """El endpoint acepta secuencia o documento: se verifica la pertenencia."""
    from app.models import Contact
    from app.services import order_by_document as modulo

    contacto = Contact(wa_id="59170029003", phone_e164="+59170029003")
    session.add(contacto)
    await session.commit()

    class SapAjeno:
        async def get_customer_purchases(self, term, top=5, skip=0):
            # Devuelve un pedido ajeno (el término coincidió con la secuencia).
            return [{"orderId": "1672200500195-01", "status": "invoiced", "value": 220}]

        async def get_order(self, numero):
            return {
                "orderId": numero,
                "status": "invoiced",
                "value": 220,
                "items": [],
                "clientProfileData": {"document": "5403339"},
            }

    monkeypatch.setattr(
        "app.sap.get_sap", lambda session: SapAjeno(), raising=True
    )

    resultado = await modulo.lookup_by_document(session, contacto, "500195")

    assert "1672200500195-01" not in resultado["text"]
    assert resultado["needs_handoff"] is True