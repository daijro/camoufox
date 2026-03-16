"""
Async version of the example — useful for scraping multiple pages concurrently.

Install deps:
    pip install cloverlabs-camoufox
    python -m camoufox fetch
"""

import asyncio
from camoufox.async_api import AsyncCamoufox

URLS = [
    "https://httpbin.org/headers",
    "https://httpbin.org/user-agent",
    "https://httpbin.org/ip",
]


async def scrape(page, url: str) -> dict:
    await page.goto(url)
    body = await page.inner_text("body")
    return {"url": url, "body": body[:300]}


async def main():
    async with AsyncCamoufox(headless=True) as browser:
        context = await browser.new_context()

        pages = [await context.new_page() for _ in URLS]
        results = await asyncio.gather(*[scrape(p, u) for p, u in zip(pages, URLS)])

        for r in results:
            print(f"\n--- {r['url']} ---")
            print(r["body"])


if __name__ == "__main__":
    asyncio.run(main())
