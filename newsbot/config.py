"""Configuration, loaded from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
STATE_DIR = PACKAGE_DIR / "state"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


@dataclass
class Config:
    # Source site
    site_url: str = "https://www.ilovetheupperwestside.com"
    feed_url: str | None = None  # explicit RSS URL; autodiscovered if unset

    # OpenAI
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    # Instagram Graph API
    ig_access_token: str | None = None
    ig_user_id: str | None = None  # the Instagram Business account ID
    graph_api_version: str = "v21.0"

    # Image hosting (the Graph API needs a public image URL). Images are
    # pushed to this GitHub repo via the contents API and served from
    # raw.githubusercontent.com — the repo must be public.
    github_token: str | None = None
    github_repo: str | None = None    # "owner/name"
    github_branch: str = "main"

    # Branding
    brand_name: str = "UWS News Daily"
    source_name: str = "I Love The Upper West Side"
    accent_color: str = "#C4472F"     # brick red
    logo_path: str | None = None      # optional PNG logo overlaid on graphics

    # Behaviour
    dry_run: bool = False             # build everything but never publish
    require_approval: bool = False    # queue posts for manual review instead of publishing
    seed_on_first_run: bool = True    # first run marks existing articles as seen, posts nothing
    max_posts_per_run: int = 2
    request_timeout: int = 30
    user_agent: str = "UWSNewsBot/1.0 (+https://github.com/{repo})"

    # State paths
    db_path: Path = field(default_factory=lambda: STATE_DIR / "newsbot.db")
    log_path: Path = field(default_factory=lambda: STATE_DIR / "log.jsonl")
    images_dir: Path = field(default_factory=lambda: STATE_DIR / "images")
    pending_dir: Path = field(default_factory=lambda: STATE_DIR / "pending")

    @classmethod
    def from_env(cls) -> "Config":
        cfg = cls(
            site_url=os.environ.get("SITE_URL", cls.site_url).rstrip("/"),
            feed_url=os.environ.get("FEED_URL") or None,
            openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
            openai_model=os.environ.get("OPENAI_MODEL", cls.openai_model),
            ig_access_token=os.environ.get("IG_ACCESS_TOKEN") or None,
            ig_user_id=os.environ.get("IG_USER_ID") or None,
            graph_api_version=os.environ.get("GRAPH_API_VERSION", cls.graph_api_version),
            github_token=os.environ.get("IMAGE_HOST_GITHUB_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or None,
            github_repo=os.environ.get("IMAGE_HOST_GITHUB_REPO")
            or os.environ.get("GITHUB_REPOSITORY")
            or None,
            github_branch=os.environ.get("IMAGE_HOST_GITHUB_BRANCH")
            or os.environ.get("GITHUB_REF_NAME")
            or cls.github_branch,
            brand_name=os.environ.get("BRAND_NAME", cls.brand_name),
            source_name=os.environ.get("SOURCE_NAME", cls.source_name),
            accent_color=os.environ.get("ACCENT_COLOR", cls.accent_color),
            logo_path=os.environ.get("LOGO_PATH") or None,
            dry_run=_env_bool("DRY_RUN", cls.dry_run),
            require_approval=_env_bool("REQUIRE_APPROVAL", cls.require_approval),
            seed_on_first_run=_env_bool("SEED_ON_FIRST_RUN", cls.seed_on_first_run),
            max_posts_per_run=_env_int("MAX_POSTS_PER_RUN", cls.max_posts_per_run),
            request_timeout=_env_int("REQUEST_TIMEOUT", cls.request_timeout),
        )
        cfg.user_agent = cfg.user_agent.format(repo=cfg.github_repo or "newsbot")
        return cfg

    def ensure_dirs(self) -> None:
        for p in (self.db_path.parent, self.images_dir, self.pending_dir):
            p.mkdir(parents=True, exist_ok=True)
