from camoufox.sync_api import Camoufox

ACCEPT_ENCODING = "identity"

with Camoufox(headless=False) as browser:
    page = browser.new_page(extra_http_headers={"accept-encoding": ACCEPT_ENCODING})
    page.goto("https://abrahamjuliot.github.io/creepjs/")
    input("Press Enter to close...")
