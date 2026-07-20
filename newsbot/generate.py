"""Generate the Instagram summary, caption, and hashtags with an LLM."""

from __future__ import annotations

import json
import logging
import re

from .config import Config
from .models import Article, PostContent

log = logging.getLogger(__name__)

IG_CAPTION_LIMIT = 2200
MAX_HASHTAGS = 25  # Instagram allows 30; leave headroom

SYSTEM_PROMPT = """\
You are the social media editor for a neighborhood-news Instagram account
covering Manhattan's Upper West Side. You write original, engaging copy.
You NEVER copy sentences from the source article — you rewrite everything
in your own words. Respond only with JSON."""

USER_PROMPT = """\
Write Instagram content for this local news article.

TITLE: {title}
PUBLISHED: {published}
ARTICLE TEXT:
{body}

Return a JSON object with exactly these keys:
- "summary": an original 75-150 word summary of the story in your own words.
  Factual, lively, neighborhood-friendly tone. No emojis inside the summary.
- "caption_hook": one short attention-grabbing opening line for the caption
  (may include 1-2 emojis).
- "hashtags": 10-15 relevant hashtags as a list of strings without the "#",
  mixing local tags (upperwestside, uws, nyc, manhattan) with story-specific ones.
"""


def _fallback_content(article: Article) -> PostContent:
    """Extractive fallback used only in dry-run mode when no API key is set."""
    sentences = re.split(r"(?<=[.!?])\s+", article.body)
    summary, words = [], 0
    for s in sentences:
        summary.append(s)
        words += len(s.split())
        if words >= 90:
            break
    return PostContent(
        summary=" ".join(summary),
        caption=f"🗞️ {article.title}",
        hashtags=["upperwestside", "uws", "nyc", "manhattan", "nycnews", "localnews"],
    )


def _clean_hashtags(raw: list) -> list[str]:
    tags, seen = [], set()
    for t in raw:
        tag = re.sub(r"[^0-9a-zA-Z_]", "", str(t).strip().lstrip("#"))
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(tag)
    return tags[:MAX_HASHTAGS]


def compose_caption(content: PostContent, article: Article, cfg: Config) -> str:
    """Assemble the final caption: hook, summary, credit, CTA, hashtags."""
    parts = [
        content.caption.strip(),
        content.summary.strip(),
        f"📰 Story via {cfg.source_name} — read the full story at the link in bio.",
    ]
    hashtag_line = " ".join(f"#{t}" for t in content.hashtags)
    caption = "\n\n".join(p for p in parts if p)
    if hashtag_line:
        caption = f"{caption}\n\n{hashtag_line}"
    if len(caption) > IG_CAPTION_LIMIT:
        overshoot = len(caption) - IG_CAPTION_LIMIT
        summary = content.summary.strip()
        trimmed = summary[: max(0, len(summary) - overshoot - 1)].rstrip() + "…"
        parts[1] = trimmed
        caption = "\n\n".join(p for p in parts if p)
        if hashtag_line:
            caption = f"{caption}\n\n{hashtag_line}"
        caption = caption[:IG_CAPTION_LIMIT]
    return caption


def generate_post(article: Article, cfg: Config) -> PostContent:
    if not cfg.openai_api_key:
        if cfg.dry_run:
            log.warning("No OPENAI_API_KEY; using extractive fallback (dry run only)")
            content = _fallback_content(article)
            content.caption = compose_caption(content, article, cfg)
            return content
        raise RuntimeError("OPENAI_API_KEY is required to generate post content")

    from openai import OpenAI  # imported lazily so dry runs don't need the package

    client = OpenAI(api_key=cfg.openai_api_key)
    response = client.chat.completions.create(
        model=cfg.openai_model,
        response_format={"type": "json_object"},
        temperature=0.7,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_PROMPT.format(
                    title=article.title,
                    published=article.published or "unknown",
                    body=article.body,
                ),
            },
        ],
    )
    data = json.loads(response.choices[0].message.content)
    content = PostContent(
        summary=str(data.get("summary", "")).strip(),
        caption=str(data.get("caption_hook", "")).strip(),
        hashtags=_clean_hashtags(data.get("hashtags", [])),
    )
    if not content.summary:
        raise ValueError("LLM returned an empty summary")
    content.caption = compose_caption(content, article, cfg)
    log.info("Generated caption (%d chars, %d hashtags)", len(content.caption), len(content.hashtags))
    return content
