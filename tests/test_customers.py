from __future__ import annotations

from sqlalchemy import select

from app.models import Contact, Conversation, Message
from app.services import customers


class FakeSap:
    async def get(self, path, params=None):
        if "4090888" in (params or {}).get("$filter", ""):
            return {
                "value": [
                    {
                        "CardCode": "T2C000009972",
                        "CardName": "JUAN DE DIOS CORONADO",
                        "CardType": "cCustomer",
                        "Cellular": "69666090",
                    }
                ]
            }
        return {"value": []}


async def test_find_by_document_masks_name():
    candidates = await customers.find_by_document(FakeSap(), "4090888")
    assert len(candidates) == 1
    assert candidates[0]["card_code"] == "T2C000009972"
    assert "***" in candidates[0]["name_masked"]
    assert candidates[0]["name"] == "JUAN DE DIOS CORONADO"


async def test_redact_document_in_message(session):
    contact = Contact(wa_id="59170000666", phone_e164="+59170000666")
    session.add(contact)
    await session.commit()
    conversation = Conversation(contact_id=contact.id)
    session.add(conversation)
    await session.flush()
    session.add(
        Message(
            conversation_id=conversation.id,
            direction="in",
            text="mi carnet es 4090888",
        )
    )
    await session.commit()

    await customers.redact_document(session, contact.id, "4090888")
    row = await session.scalar(
        select(Message).where(
            Message.conversation_id == conversation.id
        )
    )
    assert "4090888" not in (row.text or "")
    assert "[documento]" in (row.text or "")
