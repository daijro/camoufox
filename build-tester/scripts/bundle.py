"""
Manages the esbuild bundle of the checks library.
Builds checks-bundle.js from TypeScript source on first run.
"""

import subprocess
import sys
from pathlib import Path


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
