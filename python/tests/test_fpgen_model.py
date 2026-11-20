"""camoufox loads fpgen only through camoucore, which installs the pinned model first.

Left to itself, `import fpgen` downloads the first release the GitHub API
lists -- model-4/2025, whose WebGL records carry no vendor or renderer -- so a
pip-installed camoufox failed every generated launch with KeyError: 'vendor' in
webgl.py. camoucore's tests cover the install; these cover camoufox's use of it.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import camoufox

PACKAGE = Path(camoufox.__file__).resolve().parent


def test_camoufox_never_imports_fpgen_itself():
    """Every fpgen import goes through camoucore.fpgen_model.load_fpgen(), which
    installs the pinned model first. A direct import anywhere else lets fpgen fetch
    model-4/2025 before the pin is in place."""
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            if any(name == "fpgen" or name.startswith("fpgen.") for name in names):
                offenders.append(f"{path.relative_to(PACKAGE)}:{node.lineno}")
    assert offenders == []


_IMPORT_ORDER = """
import sys
from camoucore import fpgen_model
real = fpgen_model.ensure_fpgen_model
seen = []
def spy(*args, **kwargs):
    seen.append("fpgen" in sys.modules)
    return real(*args, **kwargs)
fpgen_model.ensure_fpgen_model = spy
from camoufox import {module}
{call}
print(seen)
"""


@pytest.mark.parametrize(
    "module, call",
    [
        pytest.param("fingerprints", "fingerprints._generator()", id="generate"),
        pytest.param("webgl", "webgl.firefox_gpus('win')", id="preset-or-webgl_config"),
    ],
)
def test_each_entry_point_installs_the_model_before_fpgen_loads(module, call):
    script = _IMPORT_ORDER.format(module=module, call=call)
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=PACKAGE.parent, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip().splitlines()[-1] == "[False]"
