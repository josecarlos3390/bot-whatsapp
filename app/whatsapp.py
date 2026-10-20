from __future__ import annotations

import hashlib
import hmac
import logging
import re
import uuid
from dataclasses import dataclass, field

import httpx

from .config import settings

logger = logging.getLogger(__name__)


@dataclass
class Outbound:
    kind: str = "text"  # text | buttons | cta | catalog | product | product_list
    text: str = ""
    buttons: list[dict[str, str]] = field(default_factory=list)
    cta_text: str = ""
    url: str = ""
    catalog_id: str = ""
    product_retailer_id: str = ""
    header_text: str = ""
    footer_text: str = ""
    sections: list[dict] = field(default_factory=list)
    template_name: str = ""
    template_lang: str = "es"
    template_parameters: list[str] = field(default_factory=list)
    button_text: str = ""


def _to_wa_id(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def normalize_whatsapp_text(text: str) -> str:
    """WhatsApp uses *bold*, not Markdown **bold**."""
    value = text or ""
    value = re.sub(r"\*\*(.+?)\*\*", r"*\1*", value, flags=re.DOTALL)
    value = re.sub(r"__(.+?)__", r"_\1_", value, flags=re.DOTALL)
    value = re.sub(r"^#{1,6}\s+", "", value, flags=re.MULTILINE)
    return value


class WhatsAppClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=20.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def send(self, to: str, message: Outbound) -> str:
        payload = self._payload(to, message)
        if settings.wa_dry_run or not settings.wa_access_token:
            logger.info(
                "WA dry-run -> %s: %s", _to_wa_id(to), message.text or message.kind
            )
            return f"dry-{uuid.uuid4()}"
        if not settings.wa_phone_number_id:
            raise RuntimeError("WA_PHONE_NUMBER_ID no está configurado")
        response = await self._client.post(
            (
                f"https://graph.facebook.com/{settings.wa_graph_version}/"
                f"{settings.wa_phone_number_id}/messages"
            ),
            headers={"Authorization": f"Bearer {settings.wa_access_token}"},
            json=payload,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"WhatsApp {response.status_code}: {response.text[:500]}"
            )
        return response.json()["messages"][0]["id"]

    async def send_text(self, to: str, text: str) -> str:
        return await self.send(to, Outbound(kind="text", text=text))

    async def send_media(
        self,
        to: str,
        data: bytes,
        filename: str,
        mime_type: str,
        caption: str = "",
    ) -> str:
        if settings.wa_dry_run or not settings.wa_access_token:
            logger.info("WA dry-run media -> %s: %s", _to_wa_id(to), filename)
            return f"dry-{uuid.uuid4()}"
        upload = await self._client.post(
            (
                f"https://graph.facebook.com/{settings.wa_graph_version}/"
                f"{settings.wa_phone_number_id}/media"
            ),
            headers={"Authorization": f"Bearer {settings.wa_access_token}"},
            data={"messaging_product": "whatsapp", "type": mime_type},
            files={"file": (filename, data, mime_type)},
        )
        if upload.status_code >= 400:
            raise RuntimeError(
                f"WhatsApp media {upload.status_code}: {upload.text[:500]}"
            )
        media_id = upload.json()["id"]
        kind = "image" if mime_type.startswith("image/") else "document"
        media: dict = {"id": media_id}
        if caption:
            media["caption"] = caption[:1024]
        if kind == "document":
            media["filename"] = filename[:240]
        response = await self._client.post(
            (
                f"https://graph.facebook.com/{settings.wa_graph_version}/"
                f"{settings.wa_phone_number_id}/messages"
            ),
            headers={"Authorization": f"Bearer {settings.wa_access_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": _to_wa_id(to),
                "type": kind,
                kind: media,
            },
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"WhatsApp {response.status_code}: {response.text[:500]}"
            )
        return response.json()["messages"][0]["id"]

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        if settings.wa_dry_run or not settings.wa_access_token:
            raise RuntimeError("Media no disponible en modo dry-run")
        meta = await self._client.get(
            (
                f"https://graph.facebook.com/{settings.wa_graph_version}/"
                f"{media_id}"
            ),
            headers={"Authorization": f"Bearer {settings.wa_access_token}"},
        )
        if meta.status_code >= 400:
            raise RuntimeError(
                f"WhatsApp media {meta.status_code}: {meta.text[:500]}"
            )
        info = meta.json()
        response = await self._client.get(
            info["url"],
            headers={"Authorization": f"Bearer {settings.wa_access_token}"},
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"WhatsApp media download {response.status_code}: {response.text[:300]}"
            )
        return response.content, info.get("mime_type", "application/octet-stream")

    async def send_buttons(
        self, to: str, text: str, buttons: list[dict[str, str]]
    ) -> str:
        return await self.send(to, Outbound(kind="buttons", text=text, buttons=buttons))

    async def send_cta(
        self, to: str, text: str, cta_text: str, url: str
    ) -> str:
        return await self.send(
            to, Outbound(kind="cta", text=text, cta_text=cta_text, url=url)
        )

    async def send_catalog(
        self, to: str, text: str, catalog_id: str | None = None
    ) -> str:
        return await self.send(
            to,
            Outbound(
                kind="catalog",
                text=text,
                catalog_id=catalog_id or settings.wa_catalog_id,
            ),
        )

    async def send_product(
        self,
        to: str,
        text: str,
        product_retailer_id: str,
        catalog_id: str | None = None,
    ) -> str:
        return await self.send(
            to,
            Outbound(
                kind="product",
                text=text,
                product_retailer_id=product_retailer_id,
                catalog_id=catalog_id or settings.wa_catalog_id,
            ),
        )

    async def send_product_list(
        self,
        to: str,
        text: str,
        sections: list[dict],
        catalog_id: str | None = None,
        header_text: str = "",
        footer_text: str = "",
    ) -> str:
        return await self.send(
            to,
            Outbound(
                kind="product_list",
                text=text,
                sections=sections,
                catalog_id=catalog_id or settings.wa_catalog_id,
                header_text=header_text,
                footer_text=footer_text,
            ),
        )

    async def send_template(
        self,
        to: str,
        name: str,
        language: str = "es",
        parameters: list[str] | None = None,
    ) -> str:
        return await self.send(
            to,
            Outbound(
                kind="template",
                template_name=name,
                template_lang=language,
                template_parameters=parameters or [],
            ),
        )

    async def send_list(
        self,
        to: str,
        text: str,
        sections: list[dict],
        button_text: str = "Ver opciones",
    ) -> str:
        return await self.send(
            to,
            Outbound(
                kind="list",
                text=text,
                sections=sections,
                button_text=button_text,
            ),
        )

    async def send_image(self, to: str, url: str, caption: str = "") -> str:
        return await self.send(
            to,
            Outbound(kind="image", url=url, text=caption),
        )

    def _payload(self, to: str, message: Outbound) -> dict:
        base = {"messaging_product": "whatsapp", "to": _to_wa_id(to)}
        if message.kind == "buttons":
            return {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": message.text[:1024]},
                    "action": {
                        "buttons": [
                            {
                                "type": "reply",
                                "reply": {
                                    "id": button["id"],
                                    "title": button["title"][:20],
                                },
                            }
                            for button in message.buttons[:3]
                        ]
                    },
                },
            }
        if message.kind == "cta":
            return {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "cta_url",
                    "body": {"text": message.text[:1024]},
                    "action": {
                        "name": "cta_url",
                        "parameters": {
                            "display_text": (message.cta_text or "Abrir")[:20],
                            "url": message.url,
                        },
                    },
                },
            }
        if message.kind == "catalog":
            return {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "catalog_message",
                    "body": {"text": message.text[:1024]},
                    "action": {"name": "catalog_message"},
                },
            }
        if message.kind == "product":
            return {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "product",
                    "body": {"text": message.text[:1024]},
                    "action": {
                        "catalog_id": message.catalog_id,
                        "product_retailer_id": message.product_retailer_id,
                    },
                },
            }
        if message.kind == "product_list":
            payload = {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "product_list",
                    "body": {"text": message.text[:1024]},
                    "action": {
                        "catalog_id": message.catalog_id,
                        "sections": message.sections,
                    },
                },
            }
            if message.header_text:
                payload["interactive"]["header"] = {
                    "type": "text",
                    "text": message.header_text[:60],
                }
            if message.footer_text:
                payload["interactive"]["footer"] = {
                    "text": message.footer_text[:60]
                }
            return payload
        if message.kind == "image":
            return {
                **base,
                "type": "image",
                "image": {
                    "link": message.url,
                    **(
                        {"caption": message.text[:1024]}
                        if message.text
                        else {}
                    ),
                },
            }
        if message.kind == "list":
            return {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": message.text[:1024]},
                    "action": {
                        "button": (message.button_text or "Ver opciones")[:20],
                        "sections": message.sections,
                    },
                },
            }
        if message.kind == "template":
            components = []
            if message.template_parameters:
                components = [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": value}
                            for value in message.template_parameters
                        ],
                    }
                ]
            return {
                **base,
                "type": "template",
                "template": {
                    "name": message.template_name,
                    "language": {"code": message.template_lang},
                    **({"components": components} if components else {}),
                },
            }
        return {**base, "type": "text", "text": {"body": message.text[:4096]}}


def verify_signature(raw_body: bytes, signature_header: str) -> bool:
    if not settings.wa_app_secret:
        logger.warning("WA_APP_SECRET vacío: se omite la verificación de firma")
        return True
    expected = "sha256=" + hmac.new(
        settings.wa_app_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


def extract_order(message: dict) -> dict | None:
    if message.get("type") != "order":
        return None
    order = message.get("order")
    return order if isinstance(order, dict) else None


def extract_text(message: dict) -> str:
    """Normaliza los tipos de mensaje que el bot entiende."""
    if message.get("type") == "text":
        return (message.get("text") or {}).get("body", "")
    if message.get("type") == "button":
        return (message.get("button") or {}).get("text", "")
    if message.get("type") == "interactive":
        interactive = message.get("interactive") or {}
        if "button_reply" in interactive:
            reply = interactive["button_reply"]
            return reply.get("id") or reply.get("title", "")
        if "list_reply" in interactive:
            reply = interactive["list_reply"]
            return reply.get("id") or reply.get("title", "")
        if "nfm_reply" in interactive:
            # Respuesta de un WhatsApp Flow (formulario nativo).
            return (interactive["nfm_reply"] or {}).get("response_json", "[flow]")
    for kind in ("image", "video", "document"):
        if message.get("type") == kind:
            return (message.get(kind) or {}).get("caption", f"[{kind}]")
    if message.get("type") == "audio":
        return "[audio]"  # TODO: transcribir con Whisper
    if message.get("type") == "location":
        return "[ubicación]"
    if message.get("type") == "order":
        order = message.get("order") or {}
        items = ", ".join(
            f"{item.get('product_retailer_id')} x{item.get('quantity')}"
            for item in order.get("product_items", [])
        )
        return f"Pedido de catálogo: {items}"
    return ""
