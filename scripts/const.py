#!/usr/bin/env python3

"""
Centralized constants for Camoufox build scripts.
"""

import sys

# Platform detection
WINDOWS = sys.platform.startswith("win32") or sys.platform.startswith("msys")

# Build targets and architectures
AVAILABLE_TARGETS = ["linux", "windows", "macos"]
AVAILABLE_ARCHS = ["x86_64", "arm64", "i686"]

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
PACKAGE_FILE_EXTENSIONS = {"linux": "tar.xz", "macos": "dmg", "windows": "zip"}
PACKAGE_REMOVE_PATHS = {
    "uninstall",
    "pingsender.exe",
    "pingsender",
    "vaapitest",
    "glxtest",
}
