"""Estados de pedido: código de VTEX -> respuesta del bot."""

from __future__ import annotations

from app.services import order_tracking as ot


def test_cada_estado_tiene_etiqueta_explicacion_y_paso():
    for codigo, datos in ot.STATUS_GUIDE.items():
        etiqueta, explicacion, paso = datos
        assert etiqueta and etiqueta[0].isupper(), codigo
        assert len(explicacion) > 15, codigo
        assert paso, codigo


def test_estados_principales_traducidos():
    assert ot.STATUS_LABELS["ready-for-handling"] == "Listo para preparar"
    assert ot.STATUS_LABELS["shipped"] == "En camino"
    assert ot.STATUS_LABELS["payment-pending"] == "Pendiente de pago"


def test_el_detalle_explica_el_estado():
    pedido = {
        "orderId": "1672200500195-01",
        "status": "ready-for-handling",
        "value": 220,
        "items": [
            {
                "name": "Set de 2 brocas",
                "quantity": 1,
                "skuCode": "HRRAELC030088",
            }
        ],
    }

    texto = ot.format_order(pedido)

    assert "Listo para preparar" in texto
    assert "espera ser armado" in texto
    assert "→" in texto
    assert "HRRAELC030088" in texto


def test_estado_desconocido_no_rompe():
    pedido = {
        "orderId": "X-01",
        "status": "algun-estado-nuevo",
        "statusDescription": "Novo status",
        "value": 10,
        "items": [],
    }

    texto = ot.format_order(pedido)

    assert "X-01" in texto
    assert "Novo status" in texto
