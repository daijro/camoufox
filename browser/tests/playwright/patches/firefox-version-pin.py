r"""
The build is the Firefox upstream.sh pins, and every identity claims that Firefox.

browser/upstream.sh names the Firefox release the build fetches and patches.
The binary under test must be that release (application.ini and platform.ini),
and an identity must claim the engine it runs on: a User-Agent naming another
Firefox than the one a page can feature-detect is a mismatch any site can read.
fpgen's records come from older Firefox releases, so the launchers rewrite the
version they draw, and a regression there would not show in a UA's shape.

Each OS's identity, from the launch and from NewContext, is read from
navigator.userAgent in the page and in a worker and from the User-Agent header
the request carries. Every one must be stock Firefox's shape with the pinned
major in both rv: and Firefox/.

    python browser/tests/playwright/patches/firefox-version-pin.py
"""

import asyncio
import configparser
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from helpers import launch_kwargs, resolve_binary  # noqa: E402

from ci._util import read_upstream_sh  # noqa: E402

STOCK_UA = re.compile(r"^Mozilla/5\.0 \([^)]+; rv:(\d+)\.0\) Gecko/20100101 Firefox/(\d+)\.0$")
URL = "https://version-pin.test/"
WORKER_UA = """async () => {
    const src = 'postMessage(navigator.userAgent)';
    const worker = new Worker(URL.createObjectURL(new Blob([src])));
    return await new Promise(resolve => worker.onmessage = e => resolve(e.data));
}"""


def build_versions(binary: Path) -> dict:
    from camoufox.pkgman import build_file

    versions = {}
    for name, section, key in (("application.ini", "App", "Version"),
                               ("platform.ini", "Build", "Milestone")):
        ini = configparser.ConfigParser()
        if not ini.read(build_file(binary, name), encoding="utf-8"):
            raise SystemExit(f"no {name} for {binary}")
        versions[f"{name} {key}"] = ini[section][key]
    return versions


async def claimed(page) -> dict:
    headers = {}

    async def fulfill(route):
        headers.update(route.request.headers)
        await route.fulfill(body="<title>pin</title>", content_type="text/html")

    await page.route(URL, fulfill)
    await page.goto(URL)
    return {
        "navigator.userAgent": await page.evaluate("navigator.userAgent"),
        "worker navigator.userAgent": await page.evaluate(WORKER_UA),
        "User-Agent header": headers["user-agent"],
    }


async def identities() -> dict:
    from camoufox.async_api import AsyncCamoufox, AsyncNewContext

    seen = {}
    for os_name in ("windows", "macos", "linux"):
        async with AsyncCamoufox(**launch_kwargs(os=os_name, i_know_what_im_doing=True)) as browser:
            for label, values in (
                ("launch", await claimed(await browser.new_page())),
                ("NewContext", await claimed(await (await AsyncNewContext(browser)).new_page())),
            ):
                for where, ua in values.items():
                    seen[f"{os_name} {label}, {where}"] = ua
    return seen


def main() -> int:
    binary = resolve_binary()
    pinned = read_upstream_sh()["version"]
    major = pinned.split(".", 1)[0]
    failures = []

    for where, version in build_versions(binary).items():
        print(f"  {where}: {version}")
        # application.ini carries Camoufox's release too (156.0.1-beta.32), and
        # a paired release can be a later one than upstream.sh's floor.
        if version.split("-", 1)[0] != pinned:
            failures.append(f"{where} is {version}, but upstream.sh pins Firefox {pinned}")

    for where, ua in asyncio.run(identities()).items():
        print(f"  {where}: {ua}")
        match = STOCK_UA.match(ua)
        if not match:
            failures.append(f"{where} is not stock Firefox's User-Agent shape: {ua}")
        elif match.groups() != (major, major):
            failures.append(f"{where} claims rv:{match[1]} Firefox/{match[2]}, but the build is Firefox {major}")

    print()
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print(f"PASS: the build is Firefox {pinned}, and every identity claims Firefox {major}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
