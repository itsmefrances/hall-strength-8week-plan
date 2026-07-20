"""Shared data types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ArticleStub:
    """A link discovered on the site, before the article page is fetched."""

    url: str
    title: str = ""
    published: str = ""  # ISO 8601 when known


@dataclass
class Article:
    """A fully extracted article."""

    url: str
    title: str
    body: str
    image_url: str | None = None
    published: str = ""


@dataclass
class PostContent:
    """LLM-generated content for one Instagram post."""

    summary: str
    caption: str
    hashtags: list[str] = field(default_factory=list)
