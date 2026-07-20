"""Render the branded 1080x1080 post graphic with Pillow."""

from __future__ import annotations

import logging
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from .config import Config
from .models import Article

log = logging.getLogger(__name__)

SIZE = 1080

FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
FONT_CANDIDATES_REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def _load_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _cover_crop_square(img: Image.Image, size: int) -> Image.Image:
    """Scale and center-crop to a size x size square (CSS object-fit: cover)."""
    w, h = img.size
    scale = size / min(w, h)
    img = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    w, h = img.size
    left, top = (w - size) // 2, (h - size) // 2
    return img.crop((left, top, left + size, top + size))


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int,
              draw: ImageDraw.ImageDraw, max_lines: int = 5) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(words) and len(lines) == max_lines and " ".join(lines) != " ".join(words):
        lines[-1] = lines[-1].rstrip(".,") + "…"
    return lines


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def create_graphic(article: Article, cfg: Config, out_path: Path) -> Path:
    accent = _hex_to_rgb(cfg.accent_color)
    canvas = Image.new("RGB", (SIZE, SIZE), (24, 26, 32))

    # Featured image as background, if available and fetchable.
    if article.image_url:
        try:
            resp = requests.get(
                article.image_url,
                timeout=cfg.request_timeout,
                headers={"User-Agent": cfg.user_agent},
                stream=True,
            )
            resp.raise_for_status()
            from io import BytesIO

            photo = Image.open(BytesIO(resp.content)).convert("RGB")
            canvas.paste(_cover_crop_square(photo, SIZE))
        except Exception as exc:  # any fetch/decode issue -> plain background
            log.warning("Featured image unusable (%s); using plain background", exc)

    # Dark gradient over the bottom half so the headline is readable.
    gradient = Image.new("L", (1, SIZE))
    for y in range(SIZE):
        gradient.putpixel((0, y), min(235, max(0, int((y - SIZE * 0.35) / (SIZE * 0.65) * 235))))
    black = Image.new("RGB", (SIZE, SIZE), (10, 10, 14))
    canvas = Image.composite(black, canvas, gradient.resize((SIZE, SIZE)))

    draw = ImageDraw.Draw(canvas)
    brand_font = _load_font(FONT_CANDIDATES_BOLD, 40)
    kicker_font = _load_font(FONT_CANDIDATES_BOLD, 30)
    headline_font = _load_font(FONT_CANDIDATES_BOLD, 62)
    footer_font = _load_font(FONT_CANDIDATES_REGULAR, 28)
    margin = 64

    # Brand bar (top).
    bar_h = 110
    draw.rectangle([0, 0, SIZE, bar_h], fill=accent)
    draw.text((margin, bar_h // 2), cfg.brand_name.upper(), font=brand_font,
              fill=(255, 255, 255), anchor="lm")
    if cfg.logo_path and Path(cfg.logo_path).exists():
        logo = Image.open(cfg.logo_path).convert("RGBA")
        logo.thumbnail((160, bar_h - 24))
        canvas.paste(logo, (SIZE - logo.width - margin // 2, (bar_h - logo.height) // 2), logo)

    # Headline block (bottom), laid out upward from the footer.
    kicker = "NEW ON THE UPPER WEST SIDE"
    lines = wrap_text(article.title, headline_font, SIZE - 2 * margin, draw)
    line_h = 76
    footer_y = SIZE - margin
    headline_y = footer_y - 56 - len(lines) * line_h
    kicker_y = headline_y - 56

    draw.rectangle([margin, kicker_y - 6, margin + 8, kicker_y + 34], fill=accent)
    draw.text((margin + 24, kicker_y), kicker, font=kicker_font, fill=accent)
    for i, line in enumerate(lines):
        draw.text((margin, headline_y + i * line_h), line, font=headline_font,
                  fill=(255, 255, 255))
    date = (article.published or "")[:10]
    footer = f"Source: {cfg.source_name}" + (f"  ·  {date}" if date else "")
    draw.text((margin, footer_y), footer, font=footer_font, fill=(210, 210, 210),
              anchor="lb")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "PNG")
    log.info("Graphic written to %s", out_path)
    return out_path
