"""Fetch an article page and extract title, featured image, date, and body."""

from __future__ import annotations

import json
import logging

import requests
from bs4 import BeautifulSoup

from .config import Config
from .models import Article, ArticleStub

log = logging.getLogger(__name__)

MAX_BODY_CHARS = 8000


def _meta(soup: BeautifulSoup, prop: str) -> str | None:
    tag = soup.find("meta", attrs={"property": prop}) or soup.find(
        "meta", attrs={"name": prop}
    )
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def _jsonld_article(soup: BeautifulSoup) -> dict:
    """First NewsArticle/Article/BlogPosting object found in JSON-LD, if any."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                candidates.extend(g for g in graph if isinstance(g, dict))
                continue
            if item.get("@type") in ("NewsArticle", "Article", "BlogPosting"):
                return item
    return {}


def _body_text(soup: BeautifulSoup) -> str:
    container = (
        soup.find("article")
        or soup.find(attrs={"class": lambda c: c and "entry-content" in c})
        or soup.find("main")
        or soup.body
        or soup
    )
    paragraphs = [
        p.get_text(" ", strip=True)
        for p in container.find_all("p")
        if len(p.get_text(strip=True)) > 40
    ]
    return "\n\n".join(paragraphs)[:MAX_BODY_CHARS]


def fetch_article(stub: ArticleStub, cfg: Config) -> Article:
    resp = requests.get(
        stub.url, timeout=cfg.request_timeout, headers={"User-Agent": cfg.user_agent}
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    ld = _jsonld_article(soup)

    title = (
        _meta(soup, "og:title")
        or ld.get("headline")
        or (soup.title.get_text(strip=True) if soup.title else "")
        or stub.title
    )
    image = _meta(soup, "og:image")
    if not image:
        ld_img = ld.get("image")
        if isinstance(ld_img, dict):
            image = ld_img.get("url")
        elif isinstance(ld_img, list) and ld_img:
            image = ld_img[0] if isinstance(ld_img[0], str) else ld_img[0].get("url")
        elif isinstance(ld_img, str):
            image = ld_img

    published = (
        _meta(soup, "article:published_time")
        or ld.get("datePublished")
        or stub.published
        or ""
    )
    body = _body_text(soup)
    if not body:
        raise ValueError(f"No body text extracted from {stub.url}")

    log.info("Extracted %r (%d chars, image=%s)", title, len(body), bool(image))
    return Article(
        url=stub.url, title=title.strip(), body=body, image_url=image, published=published
    )
