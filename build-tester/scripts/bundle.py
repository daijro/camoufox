"""
Manages the esbuild bundle of the checks library.
Builds checks-bundle.js from TypeScript source on first run.
"""

import subprocess
import sys
from pathlib import Path


# The checks used to run as a <script> in the served page and hand their results
# back through window.__testResults__. That stopped working when page.evaluate()
# moved into an isolated world: the runner reads those globals via evaluate() and
# wait_for_function(), which no longer see anything the page itself wrote.
#
# Running the bundle as an init script puts it in the same world the runner reads
# from, so the handoff works again -- and the checks become invisible to the page,
# which is the right shape for an antibot tester anyway. Init scripts run at
# document-start, hence the readiness wait the inline version did not need.
_RUNNER = """
(function () {
  function run() {
    Promise.resolve()
      .then(function () { return CamoufoxChecks.runAllChecks(); })
      .then(function (results) {
        window.__testResults__ = results;
        window.__testComplete__ = true;
      })
      .catch(function (e) {
        window.__testError__ = String(e);
        window.__testComplete__ = true;
      });
  }
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', run, { once: true });
  else
    run();
})();
"""


def checks_init_script(project_dir: Path) -> str:
    """Bundle plus its runner, as one init script.

    Kept in a single script so the runner sees the bundle's `CamoufoxChecks`
    binding regardless of how the world scopes top-level declarations.
    """
    return ensure_bundle(project_dir).read_text(encoding="utf-8") + _RUNNER


def ensure_bundle(project_dir: Path) -> Path:
    bundle_path = project_dir / "scripts" / "checks-bundle.js"
    if bundle_path.exists():
        return bundle_path

    node_modules = project_dir / "node_modules"
    if not node_modules.exists():
        print("ERROR: node_modules not found. Run 'npm install' first.", file=sys.stderr)
        sys.exit(1)

    esbuild = project_dir / "node_modules" / ".bin" / "esbuild"
    if sys.platform == "win32":
        esbuild_cmd_path = project_dir / "node_modules" / ".bin" / "esbuild.cmd"
        if esbuild_cmd_path.exists():
            esbuild = esbuild_cmd_path

    print("Building checks bundle (first run)...")
    entry = project_dir / "src" / "lib" / "checks" / "index.ts"
    result = subprocess.run(
        [
            str(esbuild),
            str(entry),
            "--bundle",
            "--platform=browser",
            "--target=es2017",
            "--format=iife",
            "--global-name=CamoufoxChecks",
            f"--outfile={bundle_path}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: esbuild failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"Bundle built: {bundle_path}")
    return bundle_path
