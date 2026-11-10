"""Take the README screenshots of the dashboard (needs Playwright + Chromium; not a project dependency).

rk --home .recall-kit/demo demo --reset && rk --home .recall-kit/demo ui &
python scripts/screenshot_dashboard.py http://127.0.0.1:8766
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "docs" / "img"


def main(base: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1240, "height": 820}, device_scale_factor=2)
        page.goto(base)
        page.fill("#q", "how long does the candle company have to settle a bill?")
        page.press("#q", "Enter")
        page.click("button.card >> nth=0")
        page.wait_for_selector(".versions")
        page.screenshot(path=OUT / "dashboard-memories.png")

        page.fill("input[type=date]", "2026-10-25")
        page.dispatch_event("input[type=date]", "change")
        page.wait_for_selector(".note")
        page.screenshot(path=OUT / "dashboard-time-travel.png")

        page.click("nav button:has-text('Review')")
        page.wait_for_selector("pre")
        page.screenshot(path=OUT / "dashboard-review.png", full_page=True)

        page.click("nav button:has-text('Projects')")
        page.wait_for_selector("h3")
        page.screenshot(path=OUT / "dashboard-projects.png", full_page=True)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766")
