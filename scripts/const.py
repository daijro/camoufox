#!/usr/bin/env python3

"""
Centralized constants for Camoufox build scripts.
"""

from enum import StrEnum
import sys


class BuildTarget(StrEnum):
    LINUX = "linux"
    WINDOWS = "windows"
    MACOS = "macos"


class BuildArch(StrEnum):
    X86_64 = "x86_64"
    ARM64 = "arm64"
    I686 = "i686"


AVAILABLE_TARGETS = [target.value for target in BuildTarget]
AVAILABLE_ARCHS = [arch.value for arch in BuildArch]


# Platform detection
WINDOWS = sys.platform.startswith("win32") or sys.platform.startswith("msys")

# VCS configuration
VCS_HUMAN_READABLE = {
    "hg": "Mercurial",
    "git": "Git",
}

# Bootstrap error messages
CLONE_MERCURIAL_PULL_FAIL = """
Failed to pull from hg.mozilla.org.

This is most likely because of unstable network connection.
Try running `cd %s && hg pull https://hg.mozilla.org/mozilla-unified` manually,
or download a mercurial bundle and use it:
https://firefox-source-docs.mozilla.org/contributing/vcs/mercurial_bundles.html"""

# Package configuration
PACKAGE_FILE_EXTENSIONS = {
    BuildTarget.LINUX: "tar.xz",
    BuildTarget.MACOS: "dmg",
    BuildTarget.WINDOWS: "zip",
}
PACKAGE_REMOVE_PATHS = {
    "uninstall",
    "pingsender.exe",
    "pingsender",
    "vaapitest",
    "glxtest",
}
