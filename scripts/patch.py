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

from _mixin import (
    find_src_dir,
    get_moz_target,
    get_options,
    list_patches,
    patch,
    run,
    temp_cd,
)

options, args = get_options()

"""
Main patcher functions
"""


@dataclass
class Patcher:
    """Patch and prepare the Camoufox source"""

    moz_target: str
    target: str

    def camoufox_patches(self):
        """
        Apply all patches
        """
        version, release = extract_args()
        with temp_cd(find_src_dir('.', version, release)):
            # Create the base mozconfig file
            run('cp -v ../assets/base.mozconfig mozconfig')
            # Set cross building target
            print(f'Using target: {self.moz_target}')
            self._update_mozconfig()

            if not options.mozconfig_only:
                # Apply all other patches
                for patch_file in list_patches():
                    patch(patch_file)

            print('Complete!')

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
                with open(mozconfig_backup, 'w', encoding='utf-8') as f:
                    pass

        # Read backup content
        with open(mozconfig_backup, 'r', encoding='utf-8') as f:
            content = f.read()

        # Add target option
        content += f"\nac_add_options --target={self.moz_target}\n"

        # Add target-specific mozconfig if it exists
        target_mozconfig = os.path.join("..", "assets", f"{self.target}.mozconfig")
        if os.path.exists(target_mozconfig):
            with open(target_mozconfig, 'r', encoding='utf-8') as f:
                content += f.read()

        # Calculate new hash
        new_hash = hashlib.sha256(content.encode()).hexdigest()

        # Update mozconfig
        print(f"-> Updating mozconfig, target is {self.moz_target}")
        with open(mozconfig, 'w', encoding='utf-8') as f:
            f.write(content)
        with open(mozconfig_hash, 'w', encoding='utf-8') as f:
            f.write(new_hash)


def add_rustup(*targets):
    """Add rust targets"""
    for rust_target in targets:
        run(f'~/.cargo/bin/rustup target add "{rust_target}"')


def _update_rustup(target):
    """Add rust targets for the given target"""
    if target == "linux":
        add_rustup("aarch64-unknown-linux-gnu", "i686-unknown-linux-gnu")
    elif target == "windows":
        add_rustup("x86_64-pc-windows-msvc", "aarch64-pc-windows-msvc", "i686-pc-windows-msvc")
    elif target == "macos":
        add_rustup("x86_64-apple-darwin", "aarch64-apple-darwin")


"""
Preparation
"""


def extract_args():
    """Get version and release from args"""
    if len(args) != 2:
        sys.stderr.write('error: please specify version and release of camoufox source')
        sys.exit(1)
    return args[0], args[1]


AVAILABLE_TARGETS = ["linux", "windows", "macos"]
AVAILABLE_ARCHS = ["x86_64", "arm64", "i686"]


def extract_build_target():
    """Get moz_target if passed to BUILD_TARGET environment variable"""

    if os.environ.get('BUILD_TARGET'):
        target, arch = os.environ['BUILD_TARGET'].split(',')
        assert target in AVAILABLE_TARGETS, f"Unsupported target: {target}"
        assert arch in AVAILABLE_ARCHS, f"Unsupported architecture: {arch}"
    else:
        target, arch = "linux", "x86_64"
    return target, arch


"""
Launcher
"""

if __name__ == "__main__":
    # Extract args
    VERSION, RELEASE = extract_args()

    TARGET, ARCH = extract_build_target()
    MOZ_TARGET = get_moz_target(TARGET, ARCH)
    _update_rustup(TARGET)

    # Check if the folder exists
    if not os.path.exists(f'camoufox-{VERSION}-{RELEASE}/configure.py'):
        sys.stderr.write('error: folder doesn\'t look like a Firefox folder.')
        sys.exit(1)

    # Apply the patches
    patcher = Patcher(MOZ_TARGET, TARGET)
    patcher.camoufox_patches()

    sys.exit(0)  # ensure 0 exit code
