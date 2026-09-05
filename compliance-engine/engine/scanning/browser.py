"""Playwright browser lifecycle."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import Browser, sync_playwright

from ..config import ScanningSettings

CANDIDATE_PATHS = ["/opt/pw-browsers/chromium", "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"]


def resolve_chromium(settings: ScanningSettings) -> str | None:
    if settings.chromium_path:
        return settings.chromium_path
    env = os.environ.get("CE_CHROMIUM_PATH")
    if env:
        return env
    for c in CANDIDATE_PATHS:
        if Path(c).exists():
            return c
    return None  # let Playwright use its own managed download


@contextmanager
def open_browser(settings: ScanningSettings) -> Iterator[Browser]:
    with sync_playwright() as pw:
        kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        exe = resolve_chromium(settings)
        if exe:
            kwargs["executable_path"] = exe
        browser = pw.chromium.launch(**kwargs)
        try:
            yield browser
        finally:
            browser.close()
