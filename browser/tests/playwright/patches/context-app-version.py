r"""
A NewContext() identity's navigator.appVersion follows its own user agent.

navigator.appVersion came only from the launch config, so a macOS context in
a Windows launch reported "5.0 (Windows)" beside a Macintosh user agent, in the
page and in its workers -- a mismatch a page reads in one line.
NavigatorManager::GetAppVersion derives it from the context's user agent, as
Firefox derives it from its own platform. The version the context's user agent
claims is firefox-version-pin's.

The launch identity is Windows; contexts claim macOS and Linux, so the
per-context answer cannot be the launch one by accident. The launch has
canvas noise on, since a browser without it binds its contexts to the host.

    python browser/tests/playwright/patches/context-app-version.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402

# Stock Firefox builds appVersion as "5.0 (" + nsHttpHandler's platform + ")":
# "Windows", "Macintosh", or "X11" -- plus "; Ubuntu" under the Ubuntu snap,
# whose user agent carries the same token (nsHttpHandler.cpp, InitUserAgentComponents).
PLATFORM = {"macos": "Macintosh", "linux": "X11", "windows": "Windows"}

READ = """async () => {
  const src = 'postMessage([navigator.appVersion, navigator.userAgent])';
  const w = new Worker(URL.createObjectURL(new Blob([src])));
  const worker = await new Promise(r => { w.onmessage = e => r(e.data); });
  return {window: [navigator.appVersion, navigator.userAgent], worker};
}"""


def expected_app_version(os_name: str, user_agent: str) -> str:
    platform = PLATFORM[os_name]
    if os_name == "linux" and "; Ubuntu;" in user_agent:
        platform += "; Ubuntu"
    return f"5.0 ({platform})"


def main() -> int:
    from camoufox.sync_api import Camoufox, NewContext

    failures = []
    with Camoufox(**launch_kwargs(os="windows", canvas_noise=True, i_know_what_im_doing=True)) as browser:
        launch_page = browser.new_page()
        launch_page.goto("about:blank")
        print(f"  launch: {launch_page.evaluate('navigator.appVersion')!r}")

        for os_name in ("macos", "linux", "windows"):
            context = NewContext(browser, os=os_name)
            page = context.new_page()
            page.set_content("<p>x</p>")
            seen = page.evaluate(READ)
            context.close()
            print(f"  {os_name:8s} window={seen['window']} worker={seen['worker']}")

            for where in ("window", "worker"):
                app_version, user_agent = seen[where]
                expected = expected_app_version(os_name, user_agent)
                if app_version != expected:
                    failures.append(
                        f"{os_name} {where}: appVersion {app_version!r}, expected {expected!r} for UA {user_agent!r}"
                    )

    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a context's appVersion follows its own user agent, in the page and in workers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
