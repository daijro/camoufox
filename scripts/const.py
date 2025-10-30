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
