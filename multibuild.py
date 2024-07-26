"""
Easy build CLI for Camoufox
Since Camoufox is NOT meant to be used as a daily driver, no installers are provided.
"""

import argparse
import glob
import os
import sys
from dataclasses import dataclass
from typing import List

# Constants
AVAILABLE_TARGETS = ["linux", "windows", "macos"]
AVAILABLE_ARCHS = ["x86_64", "arm64", "i686"]


def exec(cmd, exit_on_fail=True):
    print(f'\n------------\n{cmd}\n------------\n')
    retval = os.system(cmd)
    if retval != 0 and exit_on_fail:
        print("fatal error: command '{}' failed".format(cmd))
        sys.exit(1)
    return retval


@dataclass
class BSYS:
    target: str
    arch: str

    def bootstrap(self):
        exec('make bootstrap')

    def build(self):
        os.environ['BUILD_TARGET'] = f'{self.target},{self.arch}'
        exec(f'make build')

    def package(self):
        if self.arch == 'x86_64':
            _arch = 'x64'
        else:
            _arch = 'arm64'
        exec(f'make package-{self.target} arch={_arch}')

    @property
    def assets(self) -> List[str]:
        package_pattern = f'camoufox-*.en-US.*.zip'
        return glob.glob(package_pattern)

    def clean(self):
        exec('make clean')


def main():
    parser = argparse.ArgumentParser(description="Easy build CLI for Camoufox")
    parser.add_argument(
        "--target", choices=AVAILABLE_TARGETS, required=True, help="Target platform for the build"
    )
    parser.add_argument(
        "--arch", choices=AVAILABLE_ARCHS, required=True, help="Target architecture for the build"
    )
    parser.add_argument("--bootstrap", action="store_true", help="Bootstrap the build system")
    parser.add_argument(
        "--clean", action="store_true", help="Clean the build directory before starting"
    )

    args = parser.parse_args()

    builder = BSYS(args.target, args.arch)
    # Run bootstrap if requested
    if args.bootstrap:
        builder.bootstrap()
    # Clean if requested
    if args.clean:
        builder.clean()
    # Run build
    builder.build()
    # Run package
    builder.package()
    # Print assets
    print(builder.assets)


if __name__ == "__main__":
    main()
