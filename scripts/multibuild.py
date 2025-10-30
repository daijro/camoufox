"""
Easy build CLI for Camoufox

Builds multiple target/architecture combinations either sequentially or in parallel.

Options:
  -h, --help            Show this help message and exit
  --target {linux,windows,macos} [{linux,windows,macos} ...]
                        Target platforms to build
  --arch {x86_64,arm64,i686} [{x86_64,arm64,i686} ...]
                        Target architectures to build for each platform
  --bootstrap           Bootstrap the build system
  --clean               Clean the build directory before starting
  --parallel            Build all combinations in parallel (experimental)
  --sequential          Build sequentially (default, more stable)

Examples:
  # Sequential builds (one at a time):
  $ python3 multibuild.py --target linux --arch x86_64 arm64

  # Parallel builds (all at once, requires multi-core system):
  $ python3 multibuild.py --target linux windows macos --arch x86_64 arm64 --parallel

Parallel Build Details:
  - Each target/arch combination runs in a separate process
  - Isolated mozconfigs: /tmp/mozconfig-{target}-{arch}.mozconfig
  - Firefox creates separate obj-{triplet}/ directories automatically
  - All output prefixed with [target/arch] for easy tracking
  - Stable mozconfig paths enable incremental builds on subsequent runs
  - No conflicts or clobbering between builds

Performance:
  On a 64-core system, parallel mode can build 7 combinations simultaneously.
  Requires ~1GB RAM per core (Firefox build system default).

Since Camoufox is NOT meant to be used as a daily driver, no installers are provided.
"""

import argparse
import glob
import os
import sys
from dataclasses import dataclass
from typing import List
import shutil
import multiprocessing
import subprocess

from const import AVAILABLE_ARCHS, AVAILABLE_TARGETS, BuildArch, BuildTarget
from scripts._utils import panic

FIREFOX_VERSION = os.getenv("FIREFOX_VERSION")
CAMOUFOX_RELEASE = os.getenv("CAMOUFOX_RELEASE", "dev")
CAMOUFOX_SRC_DIR = f"camoufox-{FIREFOX_VERSION}-{CAMOUFOX_RELEASE}"


def get_moz_target(target, arch):
    """Get moz_target from target and arch (copied from _mixin.py)"""
    if target == BuildTarget.LINUX:
        return (
            "aarch64-unknown-linux-gnu"
            if arch == BuildArch.ARM64
            else f"{arch}-pc-linux-gnu"
        )
    if target == BuildTarget.WINDOWS:
        return f"{arch}-pc-mingw32"
    if target == BuildTarget.MACOS:
        return (
            "aarch64-apple-darwin"
            if arch == BuildArch.ARM64
            else f"{arch}-apple-darwin"
        )
    raise ValueError(f"Unsupported target: {target}")


def update_rustup(target):
    """Add rust targets for the given platform"""
    rust_targets = {
        BuildTarget.LINUX: ["aarch64-unknown-linux-gnu", "i686-unknown-linux-gnu"],
        BuildTarget.WINDOWS: [
            "x86_64-pc-windows-msvc",
            "aarch64-pc-windows-msvc",
            "i686-pc-windows-msvc",
        ],
        BuildTarget.MACOS: ["x86_64-apple-darwin", "aarch64-apple-darwin"],
    }
    for rust_target in rust_targets.get(target, []):
        os.system(f'~/.cargo/bin/rustup target add "{rust_target}"')


def run(cmd, exit_on_fail=True):
    print(f"\n------------\n{cmd}\n------------\n")
    retval = os.system(cmd)
    if retval != 0 and exit_on_fail:
        panic(f"fatal error: command '{cmd}' failed")
    return retval


def run_with_prefix(cmd, prefix, exit_on_fail=True):
    """
    Run a command and prefix all output lines with [prefix]
    Returns the exit code
    """
    print(f"[{prefix}] Running: {cmd}\n", flush=True)

    # Use unbuffered output with stdbuf on Linux (if available)
    # stdbuf needs to wrap the shell, not the command
    if shutil.which("stdbuf"):
        # Wrap the shell itself with stdbuf
        process = subprocess.Popen(
            ["stdbuf", "-oL", "-eL", "bash", "-c", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,  # Unbuffered
        )
    else:
        # macOS/Windows: fall back to regular shell execution
        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,  # Unbuffered
        )

    # Stream output with prefix in real-time
    for line in iter(process.stdout.readline, b""):
        decoded_line = line.decode("utf-8", errors="replace")
        print(f"[{prefix}] {decoded_line}", end="", flush=True)

    process.wait()

    if process.returncode != 0:
        print(
            f"[{prefix}] Command failed with exit code {process.returncode}", flush=True
        )
        if exit_on_fail:
            raise RuntimeError(f"Command failed: {cmd}")

    return process.returncode


@dataclass
class BSYS:
    target: str
    arch: str

    @staticmethod
    def bootstrap():
        """Bootstrap the build system"""
        run("make bootstrap")

    def generate_mozconfig(self, output_path, verbose=True):
        """Generate a mozconfig file for this target/arch at specified path"""
        # Read base mozconfig
        with open("firefox/assets/base.mozconfig", "r") as f:
            content = f.read()

        # Add target
        moz_target = get_moz_target(self.target, self.arch)
        content += f"\nac_add_options --target={moz_target}\n"

        # Add platform-specific mozconfig if it exists
        platform_config = f"firefox/assets/{self.target}.mozconfig"
        if os.path.exists(platform_config):
            with open(platform_config, "r") as f:
                content += f.read()

        # Write to output path
        with open(output_path, "w") as f:
            f.write(content)

        if verbose:
            print(f"Generated mozconfig for {self.target}/{self.arch} at {output_path}")

    def build(self, mozconfig_path=None, prefix=None):
        """Build the Camoufox source code"""

        # Set MOZCONFIG if provided, otherwise use BUILD_TARGET (legacy)
        if mozconfig_path:
            # For parallel builds, use absolute path to mozconfig
            abs_mozconfig = os.path.abspath(mozconfig_path)
            cmd = f"cd {CAMOUFOX_SRC_DIR} && MOZCONFIG={abs_mozconfig} ./mach build"
        else:
            os.environ["BUILD_TARGET"] = f"{self.target},{self.arch}"
            cmd = "make build"

        # Use prefixed output for parallel builds
        if prefix:
            run_with_prefix(cmd, prefix)
        else:
            run(cmd)

    def package(self, mozconfig_path=None, prefix=None):
        """Package the Camoufox source code using scripts/package.py"""

        # Build the package.py command (same for both sequential and parallel)
        fonts = "windows macos linux"
        includes = "settings/chrome.css settings/camoucfg.jvv settings/properties.json bundle/fontconfigs"

        # Set MOZCONFIG environment for parallel builds to ensure correct obj directory
        if mozconfig_path:
            abs_mozconfig = os.path.abspath(mozconfig_path)
            cmd = f"MOZCONFIG={abs_mozconfig} python3 scripts/package.py {self.target} --version {FIREFOX_VERSION} --release {CAMOUFOX_RELEASE} --arch {self.arch} --fonts {fonts} --includes {includes}"
        else:
            cmd = f"python3 scripts/package.py {self.target} --version {FIREFOX_VERSION} --release {CAMOUFOX_RELEASE} --arch {self.arch} --fonts {fonts} --includes {includes}"

        if prefix:
            run_with_prefix(cmd, prefix)
        else:
            run(cmd)

    def update_target(self):
        """Change the build target (legacy method for sequential builds)"""
        os.environ["BUILD_TARGET"] = f"{self.target},{self.arch}"
        run("make set-target")

    @property
    def assets(self) -> List[str]:
        """Get the list of assets"""
        package_pattern = f"camoufox-*-{self.target[:3]}.{self.arch}.zip"
        return glob.glob(package_pattern)

    @staticmethod
    def clean():
        """Clean the Camoufox directory"""
        run("make clean")


def run_build(target, arch):
    """
    Run the build for the given target and architecture (sequential mode)
    """
    builder = BSYS(target, arch)
    builder.update_target()
    # Run build
    builder.build()
    # Run package
    builder.package()
    # Move assets to dist
    os.makedirs("dist", exist_ok=True)
    print("Assets:", ", ".join(builder.assets))
    for asset in builder.assets:
        shutil.move(asset, f"dist/{asset}")


def run_build_parallel(target, arch):
    """
    Run the build for the given target and architecture (parallel mode)
    Each worker gets its own isolated mozconfig file
    """
    # Create prefix for all output from this build
    prefix = f"{target}/{arch}"

    print(f"\n[{prefix}] {'=' * 60}")
    print(f"[{prefix}] Starting build")
    print(f"[{prefix}] {'=' * 60}\n")

    builder = BSYS(target, arch)

    # Use consistent mozconfig path (no random suffix) to avoid rebuilds
    # This file persists between runs so build system doesn't reconfigure unnecessarily
    mozconfig_path = f"/tmp/mozconfig-{target}-{arch}.mozconfig"

    try:
        # Generate mozconfig
        print(f"[{prefix}] Generating mozconfig at {mozconfig_path}")
        builder.generate_mozconfig(mozconfig_path, verbose=False)

        # Build with isolated mozconfig
        builder.build(mozconfig_path=mozconfig_path, prefix=prefix)

        # Package using scripts/package.py (runs ./mach package + post-processing)
        builder.package(mozconfig_path=mozconfig_path, prefix=prefix)

        # Move assets to dist
        os.makedirs("dist", exist_ok=True)
        assets = builder.assets
        print(f"[{prefix}] Assets: {', '.join(assets)}")
        for asset in assets:
            shutil.move(asset, f"dist/{asset}")

        print(f"\n[{prefix}] {'=' * 60}")
        print(f"[{prefix}] Build completed successfully!")
        print(f"[{prefix}] {'=' * 60}\n")

        return True

    except Exception as e:
        print(f"\n[{prefix}] {'=' * 60}")
        print(f"[{prefix}] BUILD FAILED!")
        print(f"[{prefix}] Error: {e}")
        print(f"[{prefix}] {'=' * 60}\n")
        return False

    # Note: We intentionally don't delete mozconfig_path
    # Keeping it allows incremental builds without reconfiguration


def main():
    parser = argparse.ArgumentParser(description="Easy build CLI for Camoufox")
    parser.add_argument(
        "--target",
        choices=AVAILABLE_TARGETS,
        nargs="+",
        required=True,
        help="Target platform for the build",
    )
    parser.add_argument(
        "--arch",
        choices=AVAILABLE_ARCHS,
        nargs="+",
        required=True,
        help="Target architecture for the build",
    )
    parser.add_argument(
        "--bootstrap", action="store_true", help="Bootstrap the build system"
    )
    parser.add_argument(
        "--clean", action="store_true", help="Clean the build directory before starting"
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Build all target/arch combinations in parallel (experimental)",
    )
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="Build sequentially (default, more stable)",
    )

    args = parser.parse_args()

    # Default to sequential if neither specified
    if not args.parallel and not args.sequential:
        args.sequential = True

    # Run bootstrap if requested
    if args.bootstrap:
        BSYS.bootstrap()
        # Add all required rust targets upfront for parallel builds
        if args.parallel:
            for target in set(args.target):
                print(f"Adding rust targets for {target}...")
                update_rustup(target)

    # Clean if requested
    if args.clean:
        BSYS.clean()

    # Build all combinations
    combinations = [
        (target, arch)
        for target in args.target
        for arch in args.arch
        if (target, arch)
        not in [
            (BuildTarget.WINDOWS, BuildArch.ARM64),
            (BuildTarget.MACOS, BuildArch.I686),
        ]
    ]

    if not combinations:
        print("No valid target/arch combinations to build")
        return

    print(f"\nBuilding {len(combinations)} combination(s): {combinations}")
    print(f"Mode: {'PARALLEL' if args.parallel else 'SEQUENTIAL'}\n")

    if args.parallel:
        # Parallel mode: use multiprocessing
        # CRITICAL: Hide in-tree mozconfig to prevent race conditions
        # Multiple builds reading/checking the same file causes spurious reconfigures
        in_tree_mozconfig = f"{CAMOUFOX_SRC_DIR}/mozconfig"
        in_tree_mozconfig_backup = f"{in_tree_mozconfig}.parallel_backup"
        in_tree_hash = f"{CAMOUFOX_SRC_DIR}/mozconfig.hash"
        in_tree_hash_backup = f"{in_tree_hash}.parallel_backup"

        # Temporarily hide in-tree mozconfig files
        if os.path.exists(in_tree_mozconfig):
            os.rename(in_tree_mozconfig, in_tree_mozconfig_backup)
            print(
                f"Temporarily moved {in_tree_mozconfig} to prevent parallel build conflicts"
            )
        if os.path.exists(in_tree_hash):
            os.rename(in_tree_hash, in_tree_hash_backup)

        try:
            with multiprocessing.Pool(processes=len(combinations)) as pool:
                results = pool.starmap(run_build_parallel, combinations)

            # Check if any builds failed
            if not all(results):
                panic("\nSome builds failed!")
            else:
                print("\nAll builds completed successfully!")
        finally:
            # Restore in-tree mozconfig for sequential builds
            if os.path.exists(in_tree_mozconfig_backup):
                os.rename(in_tree_mozconfig_backup, in_tree_mozconfig)
                print(f"\nRestored {in_tree_mozconfig}")
            if os.path.exists(in_tree_hash_backup):
                os.rename(in_tree_hash_backup, in_tree_hash)
    else:
        # Sequential mode: original behavior
        for target, arch in combinations:
            run_build(target, arch)


if __name__ == "__main__":
    main()
