from __future__ import annotations

from app.services import advisors


def test_password_hash_roundtrip():
    encoded = advisors.hash_password("secreta-123")
    assert encoded.startswith("pbkdf2_sha256$")
    assert advisors.verify_password("secreta-123", encoded)
    assert not advisors.verify_password("otra", encoded)


def test_session_roundtrip(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "advisor_session_secret", "test-secret")
    token = advisors.make_session("ana")
    assert advisors.parse_session(token) == "ana"
    assert advisors.parse_session(token + "x") is None


async def test_create_and_authenticate(session):
    advisor = await advisors.create_advisor(
        session, "Ana", "clave-123", "Ana Pérez"
    )
    assert advisor.username == "ana"
    found = await advisors.authenticate(session, "ana", "clave-123")
    assert found is not None and found.id == advisor.id
    assert await advisors.authenticate(session, "ana", "mala") is None
