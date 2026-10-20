from __future__ import annotations

from app.whatsapp import extract_text, normalize_whatsapp_text


def test_parse_text_message():
    assert (
        extract_text(
            {"type": "text", "text": {"body": "hola"}}
        )
        == "hola"
    )


def test_parse_button_reply_uses_id():
    message = {
        "type": "interactive",
        "interactive": {
            "type": "button_reply",
            "button_reply": {"id": "checkout", "title": "Confirmar pedido"},
        },
    }
    assert extract_text(message) == "checkout"


def test_parse_flow_reply():
    message = {
        "type": "interactive",
        "interactive": {
            "type": "nfm_reply",
            "nfm_reply": {"response_json": '{"screen":"PAGO"}'},
        },
    }
    assert extract_text(message) == '{"screen":"PAGO"}'


def test_parse_catalog_order():
    message = {
        "type": "order",
        "order": {
            "catalog_id": "1",
            "product_items": [
                {"product_retailer_id": "FILT-001", "quantity": 2}
            ],
        },
    }
    assert "FILT-001 x2" in extract_text(message)


def test_parse_audio_marker():
    assert extract_text({"type": "audio", "audio": {}}) == "[audio]"


def test_normalize_markdown_bold():
    assert normalize_whatsapp_text("**Hola** y __mundo__") == "*Hola* y _mundo_"
    assert normalize_whatsapp_text("### Título") == "Título"
