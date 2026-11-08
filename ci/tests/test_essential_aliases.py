"""essential-fonts.json claims an alias name only where its target renders.

A name the bundled fonts.conf rewrites (Linux: Calibri -> Carlito) renders
only through its target, so the floor every identity of an OS claims may hold
it only when every base of that OS has the target. Linux's floor once carried
Calibri and Cambria, whose targets come with LibreOffice and are in neither
Ubuntu base; only a Windows font leaked into every launch rendered them.

Run:  python3 -m pytest ci/tests -q
"""

import importlib.util
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
PACKAGE = REPO / "python" / "src" / "camoufox"


def _aliases():
    sys.path.insert(0, str(REPO / "browser" / "scripts"))
    spec = importlib.util.spec_from_file_location("gen_fonts_json", REPO / "browser" / "scripts" / "gen-fonts-json.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ALIASES


ESSENTIAL = json.loads((PACKAGE / "essential-fonts.json").read_text(encoding="utf-8"))
BASES = json.loads((PACKAGE / "font-bases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("os_key", ["win", "mac", "lin"])
def test_every_essential_alias_has_its_target_in_every_base(os_key):
    aliases = _aliases()[os_key]
    for name in ESSENTIAL[os_key]:
        if name not in aliases:
            continue
        missing = [b["id"] for b in BASES[os_key] if aliases[name] not in b["fonts"]]
        assert not missing, f"{os_key}: {name} is essential, but its target {aliases[name]} is not in {missing}"


def test_linux_does_not_claim_libreoffice_aliases():
    assert "Calibri" not in ESSENTIAL["lin"] and "Cambria" not in ESSENTIAL["lin"]
