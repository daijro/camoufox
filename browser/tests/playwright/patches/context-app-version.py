r"""
A NewContext() identity's navigator.appVersion follows its own user agent.

navigator.appVersion came only from the launch config, so a macOS context in
a Windows launch reported "5.0 (Windows)" beside a Macintosh user agent, in the
page and in its workers -- a mismatch a page reads in one line. The launcher
now hands each context the appVersion it derives from that context's user
agent (setNavigatorAppVersion), so the expected value is the launcher's own
rule applied to the user agent the page sees.

The launch identity is Windows; contexts claim macOS and Linux, so the
per-context answer cannot be the launch one by accident. The launch has
canvas noise on, since a browser without it binds its contexts to the host.

    python browser/tests/playwright/patches/context-app-version.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402

READ = """async () => {
  const src = 'postMessage([navigator.appVersion, navigator.userAgent])';
  const w = new Worker(URL.createObjectURL(new Blob([src])));
  const worker = await new Promise(r => { w.onmessage = e => r(e.data); });
  return {window: [navigator.appVersion, navigator.userAgent], worker};
}"""


def main() -> int:
    from camoufox.fingerprints import _app_version_from_user_agent
    from camoufox.sync_api import Camoufox, NewContext

    failures = []
    with Camoufox(**launch_kwargs(os="windows", canvas_noise=True, i_know_what_im_doing=True)) as browser:
        for os_name in ("macos", "linux"):
            context = NewContext(browser, os=os_name)
            page = context.new_page()
            page.set_content("<p>x</p>")
            seen = page.evaluate(READ)
            context.close()
            print(f"  {os_name:8s} window={seen['window']} worker={seen['worker']}")

            for where in ("window", "worker"):
                app_version, user_agent = seen[where]
                expected = _app_version_from_user_agent(user_agent)
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
