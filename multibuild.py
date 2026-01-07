"""
Easy build CLI for Camoufox

options:
  -h, --help            show this help message and exit
  --target {linux,windows,macos} [{linux,windows,macos} ...]
                        Target platforms to build
  --arch {x86_64,arm64,i686} [{x86_64,arm64,i686} ...]
                        Target architectures to build for each platform
  --bootstrap           Bootstrap the build system
  --clean               Clean the build directory before starting

Example:
$ python3 multibuild.py --target linux windows macos --arch x86_64 arm64

Since Camoufox is NOT meant to be used as a daily driver, no installers are provided.
"""

import argparse
import glob
import os
from pathlib import Path
import sys
from dataclasses import dataclass
from typing import List
import shutil

# Constants
AVAILABLE_TARGETS = ["linux", "windows", "macos"]
AVAILABLE_ARCHS = ["x86_64", "arm64", "i686"]


def setup_linux_sysroots():
    """
    Set up symlinks required for Linux cross-compilation.
    The sysroots may be missing the libsqlite3.so symlink needed for linking.
    """
    mozbuild = Path.home() / '.mozbuild'
    sysroots = [
        ('sysroot-aarch64-linux-gnu', 'aarch64-linux-gnu'),
        ('sysroot-x86_64-linux-gnu', 'x86_64-linux-gnu'),
        ('sysroot-i686-linux-gnu', 'i686-linux-gnu'),
    ]

    for sysroot_name, lib_arch in sysroots:
        sysroot_lib = mozbuild / sysroot_name / 'usr' / 'lib' / lib_arch
        sqlite_so = sysroot_lib / 'libsqlite3.so'
        sqlite_so_0 = sysroot_lib / 'libsqlite3.so.0'

        if sysroot_lib.exists() and sqlite_so_0.exists() and not sqlite_so.exists():
            print(f"Creating libsqlite3.so symlink in {sysroot_lib}")
            sqlite_so.symlink_to('libsqlite3.so.0')


def run(cmd, exit_on_fail=True):
    print(f'\n------------\n{cmd}\n------------\n')
    retval = os.system(cmd)
    if retval != 0 and exit_on_fail:
        print(f"fatal error: command '{cmd}' failed")
        sys.exit(1)
    return retval


@dataclass
class BSYS:
    target: str
    arch: str

    @staticmethod
    def bootstrap():
        """Bootstrap the build system"""
        run('make bootstrap')

    @staticmethod
    def generate_assets_car():
        """Generate Assets.car for macOS builds"""
        run('make generate-assets-car')

    def build(self):
        """Build the Camoufox source code"""
        os.environ['BUILD_TARGET'] = f'{self.target},{self.arch}'
        run('make build')

    def package(self):
        """Package the Camoufox source code"""
        run(f'make package-{self.target} arch={self.arch}')

    def update_target(self):
        """Change the build target"""
        os.environ['BUILD_TARGET'] = f'{self.target},{self.arch}'
        run('make set-target')

    @property
    def assets(self) -> List[str]:
        """Get the list of assets"""
        package_pattern = f'camoufox-*-{self.target[:3]}.{self.arch}.zip'
        return glob.glob(package_pattern)

    @staticmethod
    def clean():
        """Clean the Camoufox directory"""
        run('make clean')


def run_build(target, arch):
    """
    Run the build for the given target and architecture
    """
    builder = BSYS(target, arch)
    builder.update_target()
    # Run build
    builder.build()
    # Run package
    builder.package()
    # Move assets to dist
    print('Assets:', ', '.join(builder.assets))
    for asset in builder.assets:
        shutil.move(asset, f'dist/{asset}')


def main():
    parser = argparse.ArgumentParser(description="Easy build CLI for Camoufox")
    parser.add_argument(
        "--target",
        choices=AVAILABLE_TARGETS,
        nargs='+',
        required=True,
        help="Target platform for the build",
    )
    parser.add_argument(
        "--arch",
        choices=AVAILABLE_ARCHS,
        nargs='+',
        required=True,
        help="Target architecture for the build",
    )
    parser.add_argument("--bootstrap", action="store_true", help="Bootstrap the build system")
    parser.add_argument(
        "--clean", action="store_true", help="Clean the build directory before starting"
    )

    args = parser.parse_args()

    # Run bootstrap if requested
    if args.bootstrap:
        BSYS.bootstrap()
    # Clean if requested
    if args.clean:
        BSYS.clean()
    # Generate Assets.car if building for macOS
    if 'macos' in args.target:
        BSYS.generate_assets_car()

    # Ensure dist directory exists
    os.makedirs('dist', exist_ok=True)

    # Set up Linux sysroot symlinks if needed
    if 'linux' in args.target:
        setup_linux_sysroots()

    # Run build
    for target in args.target:
        for arch in args.arch:
            if (target, arch) in [("windows", "arm64"), ("macos", "i686")]:
                print(f"Skipping {target} {arch}: Unsupported architecture.")
                continue
            run_build(target, arch)


if __name__ == "__main__":
    main()
