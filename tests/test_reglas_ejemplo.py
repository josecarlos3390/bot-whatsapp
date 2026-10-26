"""Reglas de ejemplo: preguntas obligatorias, devolución e indicación."""

from __future__ import annotations

from app.services import area_router, area_rules, rule_policy


def test_el_area_reconoce_plurales():
    assert "operaciones" in area_router.detect("hacen envios a Santa Cruz?")
    assert "calidad" in area_router.detect("aplican garantias?")


def test_comparacion_ignora_signos_de_puntuacion():
    from app.services.rules_engine import _same

    assert _same("envíos", "entrega?")
    assert _same("Heladeras", "heladera?")


async def test_preguntas_obligatorias_llegan_al_prompt(session):
    await area_rules.create_rule(
        session,
        area="ecommerce",
        name="Preguntas de heladeras",
        rule_type="required_questions",
        condition={"category": "Heladeras"},
        action={"questions": [{"text": "¿Cuántos litros necesitás?"}]},
        status="published",
        priority=50,
    )

    policy = await rule_policy.build(session, "busco una heladera")

    assert "Preguntar antes de cerrar" in policy.prompt_text()
    assert "litros" in policy.prompt_text()


async def test_indicacion_de_envios_llega_al_prompt(session):
    await area_rules.create_rule(
        session,
        area="operaciones",
        name="Indicación de envíos",
        rule_type="response_rule",
        condition={"category": "envíos"},
        action={"instruction": "Informar entrega en 24 horas y retiro en tienda."},
        status="published",
        priority=50,
    )

    para_envio = await rule_policy.build(session, "hacen envios a Santa Cruz?")
    para_entrega = await rule_policy.build(session, "cuanto tarda la entrega?")

    assert "retiro en tienda" in para_envio.prompt_text()
    assert "retiro en tienda" in para_entrega.prompt_text()


async def test_flujo_de_devolucion_pide_la_primera_pregunta(session):
    from app.models import Contact, Conversation
    from app.services import return_flow

    regla = await area_rules.create_rule(
        session,
        area="calidad",
        name="Devolución de licuadora",
        rule_type="return_flow",
        condition={"intent": "devolucion"},
        action={
            "questions": [
                {"text": "¿Cuándo la compraste?"},
                {"text": "¿Está sin uso?", "require_yes": True},
            ]
        },
        status="published",
        priority=60,
    )
    contacto = Contact(wa_id="59170019999", phone_e164="+59170019999")
    session.add(contacto)
    await session.flush()
    session.add(Conversation(contact_id=contacto.id))
    await session.commit()

    texto = await return_flow.start(session, contacto, regla)

    assert "1/2" in texto
    assert "¿Cuándo la compraste?" in texto
