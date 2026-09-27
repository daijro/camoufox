"""The data files that ship must not contain an identity we would refuse to use.

`camoufox.coherence` filters at draw time, so an impossible row can never reach
a page either way. This is the second filter, on the data itself: a row that
survives here is one a future refresh could ship, a consumer reading the JSON
directly would get, and a reviewer would take as real. Both filters run the same
rules -- `scripts/clean-fingerprint-data.py --write` is what makes these pass.

Dropped on 2026-09-17: 38 of 435 presets (26 with a GPU their OS cannot report,
7 pairing Apple Silicon with a core count Apple never shipped, 4 with a colour
depth their GPU contradicts, 3 with a phone viewport, 1 claiming 40 touch
points). 24 of them, macOS presets naming "Intel(R) HD Graphics 400" or "Radeon
R9 200 Series", are restored: those are the buckets Firefox reports for an
Intel Mac's GPU (see camoufox.coherence).
"""

import json
import sys
from os.path import dirname, join
from pathlib import Path

import pytest

sys.path.insert(0, join(dirname(__file__), ".."))

from camoufox import coherence  # noqa: E402
from camoufox.fingerprints import from_preset  # noqa: E402

DATA = Path(__file__).parent.parent / "camoufox"
PRESET_FILES = ("fingerprint-presets.json", "fingerprint-presets-v150.json")
OS_KEY = {"macos": "mac", "windows": "win", "linux": "lin"}


@pytest.mark.parametrize("filename", PRESET_FILES)
def test_every_bundled_preset_is_coherent_as_stored(filename):
    presets = json.loads((DATA / filename).read_text())["presets"]
    for os_name, entries in presets.items():
        assert entries, f"{filename}/{os_name} has no presets left"
        for index, preset in enumerate(entries):
            config = from_preset(preset, "152")
            violations = coherence.validate(config, OS_KEY[os_name])
            assert violations == [], (
                f"{filename} {os_name}[{index}]: "
                + "; ".join(v.detail for v in violations)
                + " -- run scripts/clean-fingerprint-data.py --write"
            )


@pytest.mark.parametrize("filename", PRESET_FILES)
def test_every_preset_gpu_has_webgl_data(filename):
    """A preset records only its GPU's name; the WebGL parameters behind it come
    from fpgen. A GPU fpgen has never seen Firefox report on that OS has none, so
    launching it would pair the name with another device's parameters."""
    from camoufox.webgl import firefox_gpus

    presets = json.loads((DATA / filename).read_text())["presets"]
    for os_name, entries in presets.items():
        known = firefox_gpus(os_name)
        for index, preset in enumerate(entries):
            gpu = (preset["webgl"]["unmaskedVendor"], preset["webgl"]["unmaskedRenderer"])
            assert gpu in known, (
                f"{filename} {os_name}[{index}]: {gpu[1]!r} has no WebGL data"
                " -- run scripts/clean-fingerprint-data.py --write"
            )
