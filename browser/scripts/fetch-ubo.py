#!/usr/bin/env python3
"""Bundle uBlock Origin, the default addon, into a build.

Every package carries AMO's newest uBO release as an extracted addon under
addons/UBO/ (Contents/Resources/addons/UBO/ on macOS), which both launchers load
from beside the binary. So the uBO a user runs, and the filter lists it blocks
with, is the one the release was tested with, and a new uBO release reaches users with
the next browser release without anyone bumping a pin.

The bundled copy keeps its packaged filter lists: its default for autoUpdate
is false (freeze_lists). Every launch is a fresh profile, and uBO's own default
downloads every list from its CDNs within a minute of each launch, which a
long-lived install does not. A policy cannot set it: any policies.json puts
Firefox in enterprise mode, which pages and the network can tell (DNS over
HTTPS stands down, for one).

A release resolves the version once and hands the same pin to its tests and to
every build through CAMOUFOX_UBO, so a uBO release landing mid-run cannot ship
untested. Without CAMOUFOX_UBO, `stage` resolves AMO's newest itself.

    scripts/fetch-ubo.py resolve      # print AMO's newest release as a pin (JSON); `pin` step output
    scripts/fetch-ubo.py stage DIR    # extract the pinned (or newest) release into DIR/addons/UBO/
"""
import argparse, hashlib, io, json, os, shutil, sys, tempfile, time, urllib.request, zipfile

# uBO's userSettingsDefault entry, as js/background.js writes it.
AUTO_UPDATE_DEFAULT = "    autoUpdate: true,\n"

AMO_ADDON = "https://addons.mozilla.org/api/v5/addons/addon/ublock-origin/"
GUID = "uBlock0@raymondhill.net"
ADDON_DIR = os.path.join("addons", "UBO")


def get(url, timeout):
    """GET with retries: a CDN hiccup should not fail a release."""
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "camoufox-build"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return resp.read()
        except OSError as e:
            if attempt == 3:
                raise
            print(f"{url}: {e}; retrying", file=sys.stderr)
            time.sleep(5 * (attempt + 1))


def pin_from_amo(addon):
    """The pin for an AMO addon record's current release."""
    if addon["guid"] != GUID:
        raise SystemExit(f"{AMO_ADDON} is {addon['guid']}, not {GUID}")
    version = addon["current_version"]
    algorithm, _, digest = version["file"]["hash"].partition(":")
    if algorithm != "sha256":
        raise SystemExit(f"AMO hashes uBlock Origin {version['version']} with {algorithm}, not sha256")
    return {"version": version["version"], "url": version["file"]["url"], "sha256": digest}


def resolve():
    return pin_from_amo(json.loads(get(AMO_ADDON, 30)))


def pin_from_env():
    """CAMOUFOX_UBO, the pin a release resolved once; None when unset."""
    raw = os.environ.get("CAMOUFOX_UBO", "").strip()
    if not raw:
        return None
    pin = json.loads(raw)
    missing = {"version", "url", "sha256"} - pin.keys()
    if missing:
        raise SystemExit(f"CAMOUFOX_UBO lacks {sorted(missing)}: {raw}")
    return pin


def freeze_lists(addon_dir):
    """Make the extracted uBO default to autoUpdate: false. Fails if uBO's
    source no longer has the one line this edits, rather than shipping a uBO
    that downloads its lists."""
    path = os.path.join(addon_dir, "js", "background.js")
    with open(path, encoding="utf-8") as f:
        source = f.read()
    if source.count(AUTO_UPDATE_DEFAULT) != 1:
        raise SystemExit(f"{path}: expected one {AUTO_UPDATE_DEFAULT.strip()!r} in "
                         "userSettingsDefault; uBO changed, update freeze_lists()")
    with open(path, "w", encoding="utf-8") as f:
        f.write(source.replace(AUTO_UPDATE_DEFAULT, "    autoUpdate: false,\n"))


def extract(xpi, pin, dest):
    """Unpack a verified XPI into dest, replacing whatever was there."""
    digest = hashlib.sha256(xpi).hexdigest()
    if digest != pin["sha256"]:
        raise SystemExit(f"uBlock Origin {pin['version']} from {pin['url']} has sha256 {digest}, "
                         f"expected {pin['sha256']}")
    with zipfile.ZipFile(io.BytesIO(xpi)) as z:
        manifest = json.loads(z.read("manifest.json"))
        gecko = manifest.get("browser_specific_settings", {}).get("gecko", {})
        if gecko.get("id") != GUID or manifest.get("version") != pin["version"]:
            raise SystemExit(f"{pin['url']} is {gecko.get('id')} {manifest.get('version')}, "
                             f"not {GUID} {pin['version']}")
        names = z.namelist()
        bad = [n for n in names if n.startswith("/") or ".." in n.split("/")]
        if bad:
            raise SystemExit(f"{pin['url']} has paths outside the addon: {bad[:5]}")
        # Into a sibling, then renamed into place, so an interrupted run never
        # leaves a manifest.json beside a half-written addon.
        parent = os.path.dirname(dest)
        os.makedirs(parent, exist_ok=True)
        tmp = tempfile.mkdtemp(prefix=".UBO.tmp-", dir=parent)
        try:
            z.extractall(tmp)
            freeze_lists(tmp)
            shutil.rmtree(dest, ignore_errors=True)
            os.replace(tmp, dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def stage(directory):
    pin = pin_from_env() or resolve()
    dest = os.path.join(directory, ADDON_DIR)
    extract(get(pin["url"], 120), pin, dest)
    print(f"uBlock Origin {pin['version']} -> {dest}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("resolve")
    p = sub.add_parser("stage")
    p.add_argument("directory", help="the build directory the launchers find files in (beside camoufox-bin)")
    args = parser.parse_args()
    if args.cmd == "resolve":
        pin = json.dumps(resolve(), separators=(",", ":"))
        print(pin)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
                fh.write(f"pin={pin}\n")
    else:
        stage(args.directory)


if __name__ == "__main__":
    main()
