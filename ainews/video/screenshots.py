"""Source-page screenshots for segment backdrops.

For each story, capture the article's own page with Playwright (already on the
box for the fetch pipeline) and use it as a dimmed, drifting backdrop behind
the segment card — the visual is literally the story.

Captures fail gracefully: anything that doesn't load, isn't http(s), or comes
back visually degenerate (a near-blank page, a full-screen cookie/consent wall)
is dropped so the renderer falls back to the branded gradient. The pure
decision logic (URL eligibility, degenerate detection from pixel stats) is
separated from the Playwright/Pillow IO so it can be tested without either.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

VIEWPORT = {"width": 1920, "height": 1080}
NAV_TIMEOUT_MS = 15000
SETTLE_MS = 2200

# Degenerate-capture thresholds (on a downsampled greyscale image):
#  - std dev below this => near-uniform (blank page / solid consent overlay)
#  - mean above this => mostly white (un-rendered / cookie wall)
MIN_STDDEV = 14.0
MAX_MEAN_BRIGHTNESS = 238.0

# Best-effort consent/cookie dismissal: button text and overlay selectors.
_CONSENT_BUTTON_RE = r"(?i)\b(accept|agree|got it|i understand|allow all|continue)\b"
_OVERLAY_SELECTORS = (
    "[id*='cookie']", "[class*='cookie']", "[id*='consent']", "[class*='consent']",
    "[class*='gdpr']", "[aria-modal='true']", ".modal-backdrop", "#onetrust-banner-sdk",
)


def is_screenshotable(url: str) -> bool:
    """Only real http(s) URLs are worth loading (skip newsletter:// etc.)."""
    try:
        parsed = urlparse(url or "")
    except Exception:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def is_degenerate(mean_brightness: float, stddev: float) -> bool:
    """Given greyscale stats, decide if a capture is unusable as a backdrop."""
    return stddev < MIN_STDDEV or mean_brightness > MAX_MEAN_BRIGHTNESS


def _image_stats(path: Path) -> "Optional[tuple[float, float]]":
    """(mean_brightness, stddev) of a downsampled greyscale image, or None."""
    try:
        from PIL import Image, ImageStat
    except ImportError:
        logger.warning("Pillow not installed — skipping degenerate detection")
        return None
    try:
        with Image.open(path) as im:
            small = im.convert("L").resize((160, 90))
            stat = ImageStat.Stat(small)
            return stat.mean[0], stat.stddev[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not analyze screenshot %s: %s", path, exc)
        return None


def _dismiss_consent(page) -> None:
    """Best-effort removal of cookie/consent UI before the screenshot."""
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        btn = page.get_by_role("button", name=__import__("re").compile(_CONSENT_BUTTON_RE))
        if btn.count() > 0:
            btn.first.click(timeout=1500)
            page.wait_for_timeout(400)
    except Exception:
        pass
    try:
        page.evaluate(
            """(sels) => {
                for (const s of sels) {
                    document.querySelectorAll(s).forEach(el => el.remove());
                }
                document.documentElement.style.overflow = 'auto';
                document.body && (document.body.style.overflow = 'auto');
            }""",
            list(_OVERLAY_SELECTORS),
        )
    except Exception:
        pass


def capture_screenshots(
    targets: "list[tuple[str, str]]",
    out_dir: Path,
) -> "dict[str, Path]":
    """Capture ``(key, url)`` targets to ``out_dir/<key>.jpg``.

    Returns key -> path only for captures that loaded AND passed degenerate
    detection. Everything else is silently omitted (renderer falls back).
    """
    eligible = [(k, u) for k, u in targets if is_screenshotable(u)]
    if not eligible:
        return {}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright not installed — no segment screenshots")
        return {}

    out_dir.mkdir(parents=True, exist_ok=True)
    good: "dict[str, Path]" = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
            viewport=VIEWPORT, locale="en-US",
        )
        page = context.new_page()
        for key, url in eligible:
            path = out_dir / f"{key}.jpg"
            try:
                page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                page.wait_for_timeout(SETTLE_MS)
                _dismiss_consent(page)
                page.screenshot(path=str(path), type="jpeg", quality=78)
            except Exception as exc:  # noqa: BLE001
                logger.info("  [Shot] %s failed: %s", key, str(exc).split(chr(10))[0][:80])
                continue

            stats = _image_stats(path)
            if stats and is_degenerate(*stats):
                logger.info("  [Shot] %s degenerate (mean=%.0f std=%.1f) — fallback",
                            key, stats[0], stats[1])
                path.unlink(missing_ok=True)
                continue
            good[key] = path
            logger.info("  [Shot] %s captured", key)

        page.close()
        context.close()
        browser.close()

    return good
