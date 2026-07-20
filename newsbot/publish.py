"""Publish a post through the Instagram Graph API (Business account required).

Two-step flow: create a media container from a public image URL + caption,
wait for it to finish processing, then publish it.
"""

from __future__ import annotations

import logging
import time

import requests

from .config import Config

log = logging.getLogger(__name__)


class InstagramError(RuntimeError):
    pass


def _graph_url(cfg: Config, path: str) -> str:
    return f"https://graph.facebook.com/{cfg.graph_api_version}/{path}"


def _check(resp: requests.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400 or "error" in data:
        raise InstagramError(
            f"Graph API error {resp.status_code}: {data.get('error', resp.text[:500])}"
        )
    return data


def publish_post(image_url: str, caption: str, cfg: Config) -> dict:
    """Returns {"id": media_id, "permalink": ...}."""
    if not (cfg.ig_access_token and cfg.ig_user_id):
        raise InstagramError("IG_ACCESS_TOKEN and IG_USER_ID are required to publish")

    container = _check(
        requests.post(
            _graph_url(cfg, f"{cfg.ig_user_id}/media"),
            data={
                "image_url": image_url,
                "caption": caption,
                "access_token": cfg.ig_access_token,
            },
            timeout=cfg.request_timeout,
        )
    )
    creation_id = container["id"]
    log.info("Created media container %s", creation_id)

    # Wait for Instagram to fetch and process the image.
    for _ in range(20):
        status = _check(
            requests.get(
                _graph_url(cfg, creation_id),
                params={"fields": "status_code", "access_token": cfg.ig_access_token},
                timeout=cfg.request_timeout,
            )
        )
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise InstagramError(f"Media container {creation_id} failed processing")
        time.sleep(3)
    else:
        raise InstagramError(f"Media container {creation_id} never finished processing")

    published = _check(
        requests.post(
            _graph_url(cfg, f"{cfg.ig_user_id}/media_publish"),
            data={"creation_id": creation_id, "access_token": cfg.ig_access_token},
            timeout=cfg.request_timeout,
        )
    )
    media_id = published["id"]
    log.info("Published Instagram media %s", media_id)

    permalink = ""
    try:
        info = _check(
            requests.get(
                _graph_url(cfg, media_id),
                params={"fields": "permalink", "access_token": cfg.ig_access_token},
                timeout=cfg.request_timeout,
            )
        )
        permalink = info.get("permalink", "")
    except InstagramError:
        pass  # permalink is nice-to-have

    return {"id": media_id, "permalink": permalink}
