from __future__ import annotations

import hashlib
import hmac
import json

import httpx

from app.config import settings
from app.db import get_session
from app.main import app
from app.models import Message
from sqlalchemy import func, select


def _payload(message_id: str = "wamid.TEST1", body: str = "hola") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "456"},
                            "contacts": [
                                {
                                    "profile": {"name": "Ana"},
                                    "wa_id": "59179462889",
                                }
                            ],
                            "messages": [
                                {
                                    "from": "59179462889",
                                    "id": message_id,
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _client(session) -> httpx.AsyncClient:
    async def override():
        yield session

    app.dependency_overrides[get_session] = override
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_webhook_verification(session, monkeypatch):
    monkeypatch.setattr(settings, "wa_verify_token", "token-123")
    async with await _client(session) as client:
        response = await client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "token-123",
                "hub.challenge": "challenge-ok",
            },
        )
        assert response.status_code == 200
        assert response.text == "challenge-ok"

        forbidden = await client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "otro",
                "hub.challenge": "x",
            },
        )
        assert forbidden.status_code == 403
    app.dependency_overrides.clear()


async def test_inbound_message_is_deduplicated(session, monkeypatch):
    monkeypatch.setattr(settings, "wa_app_secret", "secret-test")
    monkeypatch.setattr(settings, "queue_enabled", False)
    monkeypatch.setattr(settings, "wa_dry_run", True)
    monkeypatch.setattr(settings, "deepseek_api_key", "")

    raw = json.dumps(_payload()).encode()
    headers = {
        "content-type": "application/json",
        "x-hub-signature-256": _sign(raw, "secret-test"),
    }
    async with await _client(session) as client:
        first = await client.post("/webhooks/whatsapp", content=raw, headers=headers)
        second = await client.post("/webhooks/whatsapp", content=raw, headers=headers)

        assert first.status_code == 200
        assert second.status_code == 200

        inbound = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.wa_message_id == "wamid.TEST1")
        )
        assert inbound == 1

        outbound = await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.direction == "out")
        )
        assert outbound and outbound >= 1
    app.dependency_overrides.clear()


async def test_invalid_signature_is_rejected(session, monkeypatch):
    monkeypatch.setattr(settings, "wa_app_secret", "secret-test")
    raw = json.dumps(_payload()).encode()
    async with await _client(session) as client:
        response = await client.post(
            "/webhooks/whatsapp",
            content=raw,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": "sha256=deadbeef",
            },
        )
        assert response.status_code == 403
    app.dependency_overrides.clear()


async def test_simulate_endpoint_runs_demo_agent(session, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(settings, "wa_dry_run", True)
    monkeypatch.setattr(settings, "deepseek_api_key", "")

    async with await _client(session) as client:
        response = await client.post(
            "/dev/simulate",
            json={"wa_id": "59179462889", "text": "buscar filtro", "name": "Ana"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["replies"]
        assert "Filtro" in data["replies"][0]["text"]
    app.dependency_overrides.clear()
