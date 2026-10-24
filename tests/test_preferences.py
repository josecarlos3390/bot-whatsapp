"""Memoria de preferencias: no repetir preguntas y afinar búsquedas."""

from __future__ import annotations

from app.models import Contact
from app.services import preferences


def test_extrae_medida_y_presupuesto():
    aprendido = preferences.extract("busco un colchón de 2 plazas hasta 2500")
    assert aprendido["size"] == "2 plazas"
    assert aprendido["budget_max"] == 2500
    assert aprendido["scope"] == "colchones"


def test_no_inventa_si_no_hay_datos():
    assert preferences.extract("hola, qué tal") == {}


def test_resumen_para_el_prompt():
    texto = preferences.summary(
        {"size": "2 plazas", "budget_max": 2500, "scope": "colchones"}
    )
    assert "2 plazas" in texto
    assert "2500" in texto
    assert "No los vuelvas a preguntar" in texto


def test_enriquece_solo_busquedas_de_cama():
    prefs = {"size": "2 plazas"}
    assert preferences.enrich("colchon", prefs) == "colchon 2 plazas"
    assert preferences.enrich("colchon 1 plaza", prefs) == "colchon 1 plaza"
    assert preferences.enrich("lavadora", prefs) == "lavadora"


async def test_recuerda_entre_mensajes(session):
    contact = Contact(wa_id="59170000911", phone_e164="+59170000911")
    session.add(contact)
    await session.commit()

    await preferences.remember(session, contact, "busco colchon de 2 plazas")
    guardadas = await preferences.remember(session, contact, "y hasta 3000")

    assert guardadas["size"] == "2 plazas"
    assert guardadas["budget_max"] == 3000
