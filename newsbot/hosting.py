"""Host the generated graphic at a public URL.

The Instagram Graph API only accepts a public image URL, so the PNG is
committed to this (public) GitHub repo via the contents API and served
from raw.githubusercontent.com.
"""

from __future__ import annotations

import base64
import logging
import time
from pathlib import Path

import requests

from .config import Config

log = logging.getLogger(__name__)

REPO_IMAGE_DIR = "newsbot/state/images"


def host_image(local_path: Path, cfg: Config) -> str:
    if not (cfg.github_token and cfg.github_repo):
        raise RuntimeError(
            "Image hosting needs IMAGE_HOST_GITHUB_TOKEN/GITHUB_TOKEN and a repo"
        )
    repo_path = f"{REPO_IMAGE_DIR}/{local_path.name}"
    api = f"https://api.github.com/repos/{cfg.github_repo}/contents/{repo_path}"
    headers = {
        "Authorization": f"Bearer {cfg.github_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": cfg.user_agent,
    }
    payload = {
        "message": f"newsbot: add graphic {local_path.name}",
        "content": base64.b64encode(local_path.read_bytes()).decode(),
        "branch": cfg.github_branch,
    }

    # If the file already exists (rerun after a partial failure), update it.
    existing = requests.get(
        api, headers=headers, params={"ref": cfg.github_branch}, timeout=cfg.request_timeout
    )
    if existing.status_code == 200:
        payload["sha"] = existing.json()["sha"]

    resp = requests.put(api, headers=headers, json=payload, timeout=cfg.request_timeout)
    resp.raise_for_status()

    raw_url = (
        f"https://raw.githubusercontent.com/{cfg.github_repo}/"
        f"{cfg.github_branch}/{repo_path}"
    )
    _wait_until_public(raw_url, cfg)
    return raw_url


def _wait_until_public(url: str, cfg: Config, attempts: int = 10, delay: float = 3.0) -> None:
    for _ in range(attempts):
        try:
            head = requests.head(url, timeout=cfg.request_timeout,
                                 headers={"User-Agent": cfg.user_agent})
            if head.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(delay)
    raise RuntimeError(f"Hosted image never became reachable: {url}")
