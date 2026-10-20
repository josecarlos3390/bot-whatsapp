"""File-backed knowledge base for policies, stores, shipping and FAQs."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings

STOPWORDS = {
    "de", "del", "la", "las", "el", "los", "un", "una", "unos", "unas",
    "y", "o", "que", "en", "por", "para", "con", "sin", "al", "a", "es",
    "son", "como", "cuando", "donde", "cuanto", "tienen", "tiene", "hay",
    "puedo", "pueden", "hacen", "hacer", "me", "mi", "tu", "su", "se",
    "lo", "le", "les", "nos", "si", "no", "mas", "más",
}


@dataclass
class KnowledgeArticle:
    title: str
    content: str
    tags: list[str] = field(default_factory=list)
    source: str = ""
    status: str = "draft"


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.lower()


def _tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9áéíóúñü]+", _normalize(value))
        if len(token) > 2 and token not in STOPWORDS
    ]


def _parse(path: Path) -> KnowledgeArticle | None:
    text = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip().lower()] = value.strip()
            body = parts[2].lstrip("\n")
    title = meta.get("title") or path.stem.replace("-", " ").title()
    status = (meta.get("status") or "draft").lower()
    tags = [
        tag.strip()
        for tag in (meta.get("tags") or "").split(",")
        if tag.strip()
    ]
    return KnowledgeArticle(
        title=title,
        content=body.strip(),
        tags=tags,
        source=path.name,
        status=status,
    )


_cache: tuple[float, list[KnowledgeArticle]] = (0.0, [])
_cache_dir: Path | None = None


def _signature(directory: Path) -> float:
    files = list(directory.glob("*.md"))
    return max((path.stat().st_mtime for path in files), default=0.0)


def load_articles(
    directory: Path | None = None, *, force: bool = False
) -> list[KnowledgeArticle]:
    global _cache, _cache_dir
    root = Path(directory or settings.knowledge_dir)
    if not root.exists():
        return []
    signature = _signature(root)
    if not force and _cache_dir == root and _cache[0] == signature:
        return _cache[1]
    articles = []
    for path in sorted(root.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        article = _parse(path)
        if article is not None:
            articles.append(article)
    _cache = (signature, articles)
    _cache_dir = root
    return articles


def search_articles(
    articles: list[KnowledgeArticle], query: str, limit: int = 3
) -> list[dict]:
    terms = _tokens(query)
    if not terms:
        return []
    scored = []
    for article in articles:
        if article.status != "published":
            continue
        haystack = _normalize(
            " ".join([article.title, " ".join(article.tags), article.content])
        )
        title = _normalize(article.title)
        score = 0
        for term in terms:
            if term in title:
                score += 3
            if term in haystack:
                score += 1
        if score:
            scored.append((score, article))
    scored.sort(key=lambda pair: (-pair[0], pair[1].title))
    return [
        {
            "title": article.title,
            "content": article.content[:2500],
            "tags": article.tags,
            "source": article.source,
        }
        for _, article in scored[: max(int(limit), 1)]
    ]


def search(query: str, limit: int = 3) -> list[dict]:
    return search_articles(load_articles(), query, limit=limit)


def reload() -> int:
    load_articles(force=True)
    return len(_cache[1])
