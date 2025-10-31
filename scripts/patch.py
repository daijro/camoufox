#!/usr/bin/env python3

"""
The script that patches the Firefox source into the Camoufox source.
Based on LibreWolf's patch script:
https://gitlab.com/librewolf-community/browser/source/-/blob/main/scripts/librewolf-patches.py

Run:
    python3 scripts/init-patch.py <version> <release>
"""

import hashlib
import os
import shutil
import sys
from dataclasses import dataclass

from _utils import (
    find_src_dir,
    get_moz_target,
    get_options,
    list_patches,
    panic,
    patch,
    run,
    temp_cd,
    update_rustup,
)
from const import BuildArch, BuildTarget

options, args = get_options()


@dataclass
class Patcher:
    """Patch and prepare the Camoufox source"""

    moz_target: str
    target: str

    def apply_all(self):
        version, release = extract_version_and_release()

        with temp_cd(find_src_dir(".", version, release)):
            run("cp -v ../firefox/assets/base.mozconfig mozconfig")
            print(f"Using build target: {self.moz_target}")
            self._update_mozconfig()

            if not options.mozconfig_only:
                # Apply all other patches
                for patch_file in list_patches():
                    patch(patch_file)

            print("Complete!")

    def _update_mozconfig(self):
        """
        Helper for adding additional mozconfig code from assets/<target>.mozconfig
        """
        mozconfig_backup = "mozconfig.backup"
        mozconfig = "mozconfig"
        mozconfig_hash = "mozconfig.hash"

        # Create backup if it doesn't exist
        if not os.path.exists(mozconfig_backup):
            if os.path.exists(mozconfig):
                shutil.copy2(mozconfig, mozconfig_backup)
            else:
                with open(mozconfig_backup, "w", encoding="utf-8") as f:
                    pass

        # Read backup content
        with open(mozconfig_backup, "r", encoding="utf-8") as f:
            content = f.read()

        # Add target option
        content += f"\nac_add_options --target={self.moz_target}\n"

        # Add target-specific mozconfig if it exists
        target_mozconfig = os.path.join(
            "..", "firefox", "assets", f"{self.target}.mozconfig"
        )
        if os.path.exists(target_mozconfig):
            with open(target_mozconfig, "r", encoding="utf-8") as f:
                content += f.read()

        # Calculate new hash
        new_hash = hashlib.sha256(content.encode()).hexdigest()

        # Update mozconfig
        print(f"-> Updating mozconfig, target is {self.moz_target}")
        with open(mozconfig, "w", encoding="utf-8") as f:
            f.write(content)
        with open(mozconfig_hash, "w", encoding="utf-8") as f:
            f.write(new_hash)


def extract_version_and_release():
    if len(args) != 2:
        panic("error: please specify version and release of camoufox source")
    return args[0], args[1]


def extract_build_target() -> tuple[BuildTarget, BuildArch]:
    """Get moz_target if passed to BUILD_TARGET environment variable"""
    if build_target := os.environ.get("BUILD_TARGET"):
        target, arch = build_target.split(",")
        return BuildTarget(target), BuildArch(arch)
    return BuildTarget.LINUX, BuildArch.X86_64


if __name__ == "__main__":
    VERSION, RELEASE = extract_version_and_release()
    TARGET, ARCH = extract_build_target()
    MOZ_TARGET = get_moz_target(TARGET, ARCH)
    update_rustup(TARGET)

    camoufox_src_dir = f"camoufox-{VERSION}-{RELEASE}"
    if not os.path.exists(f"{camoufox_src_dir}/configure.py"):
        panic(f"error: folder '{camoufox_src_dir}' doesn't look like a Firefox folder.")

    patcher = Patcher(MOZ_TARGET, TARGET)
    patcher.apply_all()

    sys.exit(0)
