"""Discover articles on the source site.

Strategy, in order of preference:
1. Explicit FEED_URL from config.
2. Common RSS/Atom feed paths (WordPress sites answer on /feed/).
3. Feed autodiscovery via <link rel="alternate"> on the homepage.
4. Fallback: scrape article links off the homepage.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .config import Config
from .models import ArticleStub

log = logging.getLogger(__name__)

COMMON_FEED_PATHS = ["/feed/", "/feed", "/rss", "/rss.xml", "/atom.xml", "/?feed=rss2"]

# Homepage links whose path starts with one of these are navigation, not articles.
NON_ARTICLE_PREFIXES = (
    "/about", "/contact", "/advertis", "/category", "/tag", "/author",
    "/privacy", "/terms", "/newsletter", "/subscribe", "/shop", "/events",
    "/wp-", "/page/", "/search", "/feed", "/cdn-cgi",
)


def normalize_url(url: str) -> str:
    """Canonical form used for dedup: lowercase host, no query/fragment.

    The scheme is preserved (the URL is also what gets fetched); only a
    missing scheme defaults to https.
    """
    parts = urlparse(url.strip())
    scheme = parts.scheme or "https"
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((scheme, netloc, path, "", "", ""))


def _fetch(url: str, cfg: Config) -> requests.Response:
    resp = requests.get(
        url,
        timeout=cfg.request_timeout,
        headers={"User-Agent": cfg.user_agent},
    )
    resp.raise_for_status()
    return resp


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_feed(xml_bytes: bytes) -> list[ArticleStub]:
    """Minimal RSS 2.0 / Atom parser (stdlib only)."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    stubs = []
    for el in root.iter():
        kind = _strip_ns(el.tag)
        if kind not in ("item", "entry"):
            continue
        link, title, published = "", "", ""
        for child in el:
            tag = _strip_ns(child.tag)
            text = (child.text or "").strip()
            if tag == "link":
                # RSS puts the URL in text; Atom in the href attribute.
                href = child.get("href", "")
                if href and child.get("rel", "alternate") == "alternate":
                    link = href
                elif text and not link:
                    link = text
            elif tag == "title":
                title = text
            elif tag in ("pubdate", "published", "updated") and not published:
                published = text
        if link:
            stubs.append(
                ArticleStub(url=normalize_url(link), title=title, published=published)
            )
    return stubs


def _entries_from_feed(feed_url: str, cfg: Config) -> list[ArticleStub]:
    try:
        resp = _fetch(feed_url, cfg)
    except requests.RequestException as exc:
        log.debug("Feed %s not reachable: %s", feed_url, exc)
        return []
    stubs = parse_feed(resp.content)
    if stubs:
        log.info("Found %d entries via feed %s", len(stubs), feed_url)
    return stubs


def _autodiscover_feed(homepage_html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(homepage_html, "html.parser")
    link = soup.find(
        "link",
        rel=re.compile("alternate", re.I),
        type=re.compile(r"application/(rss|atom)\+xml", re.I),
    )
    if link and link.get("href"):
        return urljoin(base_url, link["href"])
    return None


def _looks_like_article_path(path: str) -> bool:
    if not path or path == "/":
        return False
    lower = path.lower()
    if any(lower.startswith(p) for p in NON_ARTICLE_PREFIXES):
        return False
    # WordPress permalinks: /YYYY/MM/slug or /some-multi-word-slug
    if re.match(r"^/\d{4}/\d{2}/", lower):
        return True
    slug = lower.strip("/").split("/")[-1]
    return "-" in slug and len(slug) > 10


def _scrape_homepage(homepage_html: str, cfg: Config) -> list[ArticleStub]:
    soup = BeautifulSoup(homepage_html, "html.parser")
    site_host = urlparse(cfg.site_url).netloc.lower().removeprefix("www.")
    seen: dict[str, ArticleStub] = {}

    # Prefer links inside <article> blocks or headline tags, then any candidate link.
    scopes = soup.find_all("article") or [soup]
    for scope in scopes:
        for a in scope.find_all("a", href=True):
            url = urljoin(cfg.site_url + "/", a["href"])
            parts = urlparse(url)
            if parts.netloc.lower().removeprefix("www.") != site_host:
                continue
            if not _looks_like_article_path(parts.path):
                continue
            norm = normalize_url(url)
            title = a.get_text(" ", strip=True)
            if norm not in seen or (title and not seen[norm].title):
                seen[norm] = ArticleStub(url=norm, title=title)
    log.info("Scraped %d candidate article links from homepage", len(seen))
    return list(seen.values())


def discover_articles(cfg: Config) -> list[ArticleStub]:
    """Return current articles on the site, newest data the site exposes."""
    feed_urls = [cfg.feed_url] if cfg.feed_url else [
        cfg.site_url + p for p in COMMON_FEED_PATHS
    ]
    for feed_url in feed_urls:
        stubs = _entries_from_feed(feed_url, cfg)
        if stubs:
            return stubs

    try:
        homepage = _fetch(cfg.site_url, cfg).text
    except requests.RequestException as exc:
        log.error("Homepage %s unreachable: %s", cfg.site_url, exc)
        return []

    discovered = _autodiscover_feed(homepage, cfg.site_url)
    if discovered:
        stubs = _entries_from_feed(discovered, cfg)
        if stubs:
            return stubs

    return _scrape_homepage(homepage, cfg)
