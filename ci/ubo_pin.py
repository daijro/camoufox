#!/usr/bin/env python3
"""Move the uBlock Origin pin in python/src/camoufox/addons.json to AMO's current release.

.github/workflows/ubo-bump.yml runs this a week before each release train and
opens a pull request with the result, so a new uBO reaches users only after the
test pipeline has run on it.

    python3 -m ci.ubo_pin    # rewrite addons.json when AMO's release differs; output `version`
"""

from __future__ import annotations

import json
import sys

from ._util import REPO_ROOT, die, http_json, log, set_output

PIN_FILE = REPO_ROOT / "python" / "src" / "camoufox" / "addons.json"
AMO_ADDON = "https://addons.mozilla.org/api/v5/addons/addon/ublock-origin/"
GUID = "uBlock0@raymondhill.net"


def pin_from_amo(addon: dict) -> dict:
    """The addons.json entry for an AMO addon's current release."""
    if addon["guid"] != GUID:
        die(f"{AMO_ADDON} is {addon['guid']}, not {GUID}")
    version = addon["current_version"]
    algorithm, _, digest = version["file"]["hash"].partition(":")
    if algorithm != "sha256":
        die(f"AMO hashes uBlock Origin {version['version']} with {algorithm}, not sha256")
    return {"version": version["version"], "url": version["file"]["url"], "sha256": digest}


def main() -> int:
    pins = json.loads(PIN_FILE.read_text(encoding="utf-8"))
    current = pin_from_amo(http_json(AMO_ADDON))
    if current == pins["UBO"]:
        log(f"uBlock Origin {current['version']} is already pinned")
        return 0
    log(f"uBlock Origin {pins['UBO']['version']} -> {current['version']}")
    pins["UBO"] = current
    PIN_FILE.write_text(json.dumps(pins, indent=1) + "\n", encoding="utf-8")
    set_output("version", current["version"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
