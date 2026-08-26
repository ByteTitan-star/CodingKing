"""Capture README showcase PNGs from docs/showcase/demo.html (no API key required)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "docs" / "showcase" / "demo.html"
OUT = ROOT / "docs" / "showcase" / "assets"


def main() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Install Playwright first: pip install playwright && playwright install chromium"
        ) from exc

    if not DEMO.is_file():
        raise SystemExit(f"Missing demo page: {DEMO}")

    OUT.mkdir(parents=True, exist_ok=True)
    url = DEMO.as_uri()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url, wait_until="networkidle")

        page.locator("#workspace-demo").screenshot(path=str(OUT / "product-workspace.png"))
        page.locator("#diff-demo").screenshot(path=str(OUT / "product-diff.png"))

        browser.close()

    print(f"Wrote {OUT / 'product-workspace.png'}")
    print(f"Wrote {OUT / 'product-diff.png'}")


if __name__ == "__main__":
    main()
