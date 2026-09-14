"""Local-only PointerEvent reproduction; no website or proxy is required."""

import argparse
import json

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", help="Path to a Camoufox browser executable")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    options = {"headless": not args.headed}
    if args.executable:
        options["executable_path"] = args.executable
    with sync_playwright() as playwright:
        browser = playwright.firefox.launch(**options)
        try:
            page = browser.new_page(viewport={"width": 800, "height": 600})
            page.set_content("<body style='margin:0;height:600px'>Pointer fixture</body>")
            page.evaluate("""() => {
                window.events = [];
                for (const type of ['pointermove', 'pointerdown', 'pointerup']) {
                    document.addEventListener(type, e => events.push({
                        type: e.type, pointerType: e.pointerType, isTrusted: e.isTrusted
                    }));
                }
            }""")
            page.mouse.move(100, 100)
            page.mouse.down()
            page.mouse.move(130, 120)
            page.mouse.up()
            events = page.evaluate("events")
            print(json.dumps({"version": browser.version, "headless": not args.headed,
                              "events": events}), flush=True)
            assert {e["type"] for e in events} == {"pointermove", "pointerdown", "pointerup"}
            assert all(e["pointerType"] == "mouse" for e in events), events
        finally:
            browser.close()


if __name__ == "__main__":
    main()
