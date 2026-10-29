"""Salud del envío: cuando el bot no puede responder."""

from __future__ import annotations

from app.services import outbox_health


def _limpiar() -> None:
    outbox_health.reset()


def test_un_envio_ok_resetea_los_fallos():
    _limpiar()
    outbox_health.record_failure("error 1")
    outbox_health.record_success()

    assert outbox_health.status()["fallos_seguidos"] == 0


def test_tres_fallos_seguidos_generan_alerta():
    _limpiar()
    for _ in range(3):
        outbox_health.record_failure("131030 recipient not in allowed list")

    estado = outbox_health.status()

    assert estado["alerta"] is True
    assert estado["fallos_seguidos"] == 3
    assert "131030" in estado["ultimo_error"]


def test_un_fallo_no_alerta():
    _limpiar()
    outbox_health.record_failure("timeout")

    assert outbox_health.status()["alerta"] is False


def test_el_estado_informa_el_ultimo_ok():
    _limpiar()
    outbox_health.record_success()

    assert outbox_health.status()["ultimo_ok"] is not None
