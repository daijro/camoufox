"""
Quick example to test cloverlabs-camoufox.

Install deps:
    pip install cloverlabs-camoufox
    python -m camoufox fetch
"""

from camoufox.sync_api import Camoufox

with Camoufox(headless=False) as browser:
    page = browser.new_page()

    # Visit a fingerprint test page
    page.goto("https://abrahamjuliot.github.io/creepjs/")
    page.wait_for_load_state("networkidle", timeout=30_000)

    title = page.title()
    print(f"Page title: {title}")

    # Grab the trust score CreepJS assigns
    score_el = page.query_selector("#creep-results .grade")
    if score_el:
        print(f"CreepJS trust grade: {score_el.inner_text()}")
    else:
        print("Score element not found — page may still be loading.")

    # Print the spoofed user-agent the browser reported
    ua = page.evaluate("navigator.userAgent")
    print(f"User-Agent: {ua}")

    input("\nPress Enter to close the browser...")
