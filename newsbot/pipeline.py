"""Orchestrate one full run: discover -> generate -> render -> publish -> log."""

from __future__ import annotations

import hashlib
import logging
import re

from .config import Config
from .extract import fetch_article
from .generate import generate_post
from .graphic import create_graphic
from .hosting import host_image
from .models import ArticleStub
from .monitor import discover_articles
from .publish import publish_post
from .storage import Storage

log = logging.getLogger(__name__)


def _slug(url: str) -> str:
    tail = re.sub(r"[^0-9a-zA-Z-]", "", url.rstrip("/").rsplit("/", 1)[-1])[:60]
    digest = hashlib.sha1(url.encode()).hexdigest()[:8]
    return f"{tail}-{digest}" if tail else digest


def run_once(cfg: Config) -> int:
    """Process new articles. Returns the number of posts published/queued."""
    cfg.ensure_dirs()
    store = Storage(cfg.db_path, cfg.log_path)
    try:
        return _run(cfg, store)
    finally:
        store.close()


def _run(cfg: Config, store: Storage) -> int:
    articles = discover_articles(cfg)
    if not articles:
        log.warning("No articles discovered; nothing to do")
        store.log_event("run_empty")
        return 0

    # First run: remember everything currently on the site without posting,
    # so enabling the bot doesn't flood the account with old stories.
    if store.is_empty() and cfg.seed_on_first_run:
        for stub in articles:
            store.mark(stub.url, "seeded", title=stub.title)
        log.info("First run: seeded %d existing articles, no posts made", len(articles))
        return 0

    new = [a for a in articles if not store.is_processed(a.url)]
    if not new:
        log.info("No new articles (checked %d)", len(articles))
        return 0

    # Feeds list newest first; post oldest-first so the account reads chronologically.
    queue = list(reversed(new))[: cfg.max_posts_per_run]
    skipped = len(new) - len(queue)
    if skipped:
        log.info("Rate limit: deferring %d additional new article(s) to later runs", skipped)

    published = 0
    for stub in queue:
        try:
            published += _process_one(stub, cfg, store)
        except Exception as exc:
            log.exception("Failed processing %s", stub.url)
            store.mark(stub.url, "error", title=stub.title, error=str(exc)[:500])
    return published


def _process_one(stub: ArticleStub, cfg: Config, store: Storage) -> int:
    log.info("Processing new article: %s", stub.url)
    article = fetch_article(stub, cfg)
    content = generate_post(article, cfg)
    image_path = cfg.images_dir / f"{_slug(article.url)}.png"
    create_graphic(article, cfg, image_path)

    if cfg.dry_run:
        preview = cfg.pending_dir / f"{_slug(article.url)}.txt"
        preview.write_text(content.caption, encoding="utf-8")
        log.info("[dry run] caption -> %s, graphic -> %s", preview, image_path)
        store.mark(article.url, "pending", title=article.title)
        return 1

    hosted_url = host_image(image_path, cfg)

    if cfg.require_approval:
        preview = cfg.pending_dir / f"{_slug(article.url)}.txt"
        preview.write_text(f"{hosted_url}\n\n{content.caption}", encoding="utf-8")
        store.mark(article.url, "pending", title=article.title, image_url=hosted_url)
        log.info("Queued for manual approval: %s", preview)
        return 1

    result = publish_post(hosted_url, content.caption, cfg)
    store.mark(
        article.url,
        "posted",
        title=article.title,
        ig_post_id=result["id"],
        ig_permalink=result.get("permalink", ""),
        image_url=hosted_url,
    )
    log.info("Posted %s -> %s", article.url, result.get("permalink") or result["id"])
    return 1
