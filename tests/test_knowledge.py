from __future__ import annotations

from pathlib import Path

from app.agent import Toolbox
from app.models import Contact
from app.services import knowledge


def test_knowledge_search_published_only(tmp_path: Path):
    (tmp_path / "envios.md").write_text(
        """---
title: Envíos
status: published
tags: envio, domicilio
---

## Cobertura
Entregamos en Santa Cruz y Warnes.
""",
        encoding="utf-8",
    )
    (tmp_path / "garantias.md").write_text(
        """---
title: Garantías
status: draft
tags: garantia
---

## Cobertura
Pendiente.
""",
        encoding="utf-8",
    )
    articles = knowledge.load_articles(tmp_path, force=True)
    assert len(articles) == 2
    results = knowledge.search_articles(articles, "envío a Warnes")
    assert len(results) == 1
    assert results[0]["title"] == "Envíos"
    assert "Warnes" in results[0]["content"]


def test_knowledge_search_draft_only_returns_empty(tmp_path: Path):
    (tmp_path / "x.md").write_text(
        "---\ntitle: X\nstatus: draft\n---\n\nTexto",
        encoding="utf-8",
    )
    articles = knowledge.load_articles(tmp_path, force=True)
    assert knowledge.search_articles(articles, "texto") == []


async def test_knowledge_tool(session, monkeypatch):
    contact = Contact(wa_id="59170000666", phone_e164="+59170000666")
    session.add(contact)
    await session.commit()
    monkeypatch.setattr(
        knowledge,
        "search",
        lambda query, limit=3: [
            {
                "title": "Envíos",
                "content": "Entregamos en Warnes.",
                "tags": ["envio"],
                "source": "envios.md",
            }
        ],
    )
    toolbox = Toolbox(session, contact)
    result = await toolbox.tool_search_knowledge("envío a Warnes")
    assert result["ok"] is True
    assert result["articles"][0]["title"] == "Envíos"
