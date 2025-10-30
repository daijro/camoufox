#!/usr/bin/env python3

"""
Common functions used across the Camoufox build system.
Not meant to be called directly.
"""

import contextlib
import fnmatch
import optparse
import os
import re
import sys
import time
from typing import NoReturn

from const import BuildArch, BuildTarget
from pathlib import Path

start_time = time.time()


@contextlib.contextmanager
def temp_cd(path: Path | str):
    """Temporarily change to a different working directory"""
    _old_cwd = os.getcwd()
    abs_path = os.path.abspath(path)
    assert os.path.exists(abs_path), f"{abs_path} does not exist."
    os.chdir(abs_path)

    try:
        yield
    finally:
        os.chdir(_old_cwd)


def get_options():
    """Get options"""
    parser = optparse.OptionParser()
    parser.add_option(
        "--mozconfig-only", dest="mozconfig_only", default=False, action="store_true"
    )
    parser.add_option(
        "-P",
        "--no-settings-pane",
        dest="settings_pane",
        default=True,
        action="store_false",
    )
    return parser.parse_args()


def find_src_dir(
    root_dir: str = ".",
    version: str | None = None,
    release: str | None = None,
):
    """Get the source directory"""
    if version and release:
        name = os.path.join(root_dir, f"camoufox-{version}-{release}")
        assert os.path.exists(name), f"{name} does not exist."
        return name
    folders = os.listdir(root_dir)
    for folder in folders:
        if os.path.isdir(folder) and folder.startswith("camoufox-"):
            return os.path.join(root_dir, folder)
    raise FileNotFoundError("No camoufox-* folder found")


def get_moz_target(target: str | BuildTarget, arch: str | BuildArch) -> str:
    """Get moz_target from target and arch"""
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


def list_files(root_dir: str, suffix: str):
    """List files in a directory"""
    for root, _, files in os.walk(root_dir):
        for file in fnmatch.filter(files, suffix):
            full_path = os.path.join(root, file)
            relative_path = os.path.relpath(full_path, root_dir)
            yield os.path.join(root_dir, relative_path).replace("\\", "/")


def list_patches(
    root_dir: str = "../firefox/patches",
    suffix: str = "*.patch",
):
    """List all patch files"""
    return sorted(list_files(root_dir, suffix), key=os.path.basename)


def is_bootstrap_patch(name: str) -> bool:
    return bool(re.match(r"\d+\-.*", os.path.basename(name)))


def script_exit(statuscode) -> NoReturn:
    """Exit the script"""
    if (time.time() - start_time) > 60:
        elapsed = time.strftime("%H:%M:%S", time.gmtime(time.time() - start_time))
        print(f"\n\aElapsed time: {elapsed}", flush=True)
    sys.exit(statuscode)


def run(
    cmd: str,
    exit_on_fail: bool = True,
    do_print: bool = True,
) -> int | None:
    """Run a command"""
    if not cmd:
        return None
    if do_print:
        print(cmd, flush=True)
    retval = os.system(cmd)
    if retval != 0 and exit_on_fail:
        print(f"fatal error: command '{cmd}' failed", flush=True)
        script_exit(1)
    return retval


def patch(
    patchfile: str,
    reverse: bool = False,
    silent: bool = False,
) -> None:
    """Run a patch file"""
    if reverse:
        cmd = f"patch -p1 -R -i {patchfile}"
    else:
        cmd = f"patch -p1 -i {patchfile}"
    if silent:
        cmd += " > /dev/null"
    else:
        print(f"\n*** -> {cmd}", flush=True)
    run(cmd)


def panic(msg: str) -> NoReturn:
    sys.stderr.write(msg)
    sys.exit(1)


__all__ = [
    "get_moz_target",
    "list_patches",
    "patch",
    "run",
    "script_exit",
    "temp_cd",
    "get_options",
    "panic",
]


if __name__ == "__main__":
    panic("This is a module, not meant to be called directly.")
