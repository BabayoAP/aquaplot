#!/usr/bin/env python3
"""Walk the two-minute path in a real browser and save screenshots to docs/screenshots/.

Run against a server started with the labelled demo data, so the dashboard has series:

    AQUAPLOT_DB=/tmp/demo.db AQUAPLOT_SEED_DEMO=1 .venv/bin/uvicorn aquaplot.app:app --port 8766 &
    .venv/bin/python scripts/screenshots.py --url http://127.0.0.1:8766

Needs Playwright with Chromium (``pip install playwright && playwright install chromium``).
It also fails loudly if any page throws a JavaScript error, so it doubles as a smoke test.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"


async def main(url: str) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        phone = await browser.new_page(viewport={"width": 420, "height": 860}, device_scale_factor=2)
        desk = await browser.new_page(viewport={"width": 1200, "height": 900})
        for page in (phone, desk):
            page.on("pageerror", lambda e: errors.append(str(e)))

        # The sample check, as a judge meets it from /try.
        await phone.goto(f"{url}/try")
        await phone.wait_for_selector("#step2:not([hidden]) .thumb img")
        await phone.click("#step2 [data-go=animals]")
        await phone.fill("#picksearch", "two tails")
        await phone.wait_for_timeout(300)
        await phone.locator("#picker button", has_text="tonefl").first.click()
        await phone.screenshot(path=OUT / "1-identify.png")
        await phone.click("#animals [data-go=step3]")
        await phone.locator("#personquestions button", has_text="Nothing unusual").first.click()
        await phone.locator("#personquestions button", has_text="A path runs alongside").first.click()
        await phone.click("#submit")
        await phone.wait_for_selector("#step4:not([hidden])", timeout=60000)
        await phone.wait_for_timeout(1200)
        card = phone.locator("#queue > div").first
        await card.screenshot(path=OUT / "2-second-opinion.png")
        await card.locator("button", has_text="Mayfly").click()
        await phone.click("#applyreview")
        await phone.wait_for_selector("#result:not([hidden])", timeout=60000)
        await phone.wait_for_timeout(1200)  # let the smooth scroll to the top finish
        await phone.screenshot(path=OUT / "3-result.png")

        await desk.goto(f"{url}/dashboard")
        await desk.wait_for_timeout(2500)
        await desk.screenshot(path=OUT / "4-dashboard.png", full_page=True)
        sites = await (await desk.request.get(f"{url}/api/sites")).json()
        declining = next((s for s in sites["sites"] if s["trend"]["direction"] == "declining"), None)
        if declining:
            await desk.goto(f"{url}/site/{declining['site_key']}")
            await desk.wait_for_selector("#chart svg")
            await desk.screenshot(path=OUT / "5-site-trend.png")
        await desk.goto(f"{url}/about")
        await desk.wait_for_timeout(800)
        await desk.screenshot(path=OUT / "0-about.png")
        await browser.close()
    if errors:
        print("JavaScript errors:\n" + "\n".join(errors), file=sys.stderr)
        return 1
    print(f"screenshots written to {OUT}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    sys.exit(asyncio.run(main(parser.parse_args().url.rstrip("/"))))
