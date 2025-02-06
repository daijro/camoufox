#!/usr/bin/env python3

import argparse
import glob
import os
import shutil
import sys
import tempfile
from shlex import join

from _mixin import find_src_dir, get_moz_target, list_files, run, temp_cd

UNNEEDED_PATHS = {'uninstall', 'pingsender.exe', 'pingsender', 'vaapitest', 'glxtest'}


def add_includes_to_package(package_file, includes, fonts, new_file, target):
    with tempfile.TemporaryDirectory() as temp_dir:
        # Extract package
        run(join(['7z', 'x', package_file, f'-o{temp_dir}']), exit_on_fail=False)
        # Delete package_file
        os.remove(package_file)
        if package_file.endswith('.tar.xz'):
            # Rerun on the tar file
            package_tar = package_file[:-3]  # Remove ".xz"
            return add_includes_to_package(
                package_file=os.path.join(temp_dir, package_tar),
                includes=includes,
                fonts=fonts,
                new_file=new_file,
                target=target,
            )

        if target == 'macos':
            # Move Camoufox/Camoufox.app -> Camoufox.app
            nightly_dir = os.path.join(temp_dir, 'Camoufox')
            shutil.move(
                os.path.join(nightly_dir, 'Camoufox.app'), os.path.join(temp_dir, 'Camoufox.app')
            )
            # Remove old app dir and all content in it
            shutil.rmtree(nightly_dir)
        else:
            # Move contents out of camoufox folder if it exists
            old_camoufox_dir = os.path.join(temp_dir, 'camoufox')
            camoufox_dir = os.path.join(temp_dir, 'camoufox-folder')
            if os.path.exists(old_camoufox_dir):
                # Rename camoufox_dir
                os.rename(old_camoufox_dir, camoufox_dir)
                for item in os.listdir(camoufox_dir):
                    shutil.move(os.path.join(camoufox_dir, item), temp_dir)
                os.rmdir(camoufox_dir)

        # Create target_dir
        if target == 'macos':
            target_dir = os.path.join(temp_dir, 'Camoufox.app', 'Contents', 'Resources')
        else:
            target_dir = temp_dir

        # Add includes
        for include in includes or []:
            if os.path.exists(include):
                if os.path.isdir(include):
                    shutil.copytree(
                        include,
                        os.path.join(target_dir, os.path.basename(include)),
                        dirs_exist_ok=True,
                    )
                else:
                    shutil.copy2(include, target_dir)

        # Add the font folders under fonts/
        fonts_dir = os.path.join(target_dir, 'fonts')
        if target == 'linux':
            for font in fonts or []:
                shutil.copytree(
                    os.path.join('bundle', 'fonts', font),
                    os.path.join(fonts_dir, font),
                    dirs_exist_ok=True,
                )
        # Non-linux systems cannot read fonts within subfolders.
        # Instead, we walk the fonts/ directory and copy all files.
        else:
            os.makedirs(fonts_dir, exist_ok=True)
            for font in fonts or []:
                for file in list_files(root_dir=os.path.join('bundle', 'fonts', font), suffix='*'):
                    shutil.copy2(file, os.path.join(fonts_dir, os.path.basename(file)))

        # Remove unneeded paths
        for path in UNNEEDED_PATHS:
            if os.path.isdir(os.path.join(target_dir, path)):
                shutil.rmtree(os.path.join(target_dir, path), ignore_errors=True)
            elif os.path.exists(os.path.join(target_dir, path)):
                os.remove(os.path.join(target_dir, path))

        # Update package
        run(join(['7z', 'u', new_file, f'{temp_dir}/*', '-r', '-mx=9']))


def get_args():
    """Get CLI parameters"""
    parser = argparse.ArgumentParser(
        description='Package Camoufox for different operating systems.'
    )
    parser.add_argument('os', choices=['linux', 'macos', 'windows'], help='Target operating system')
    parser.add_argument(
        '--includes', nargs='+', help='List of files or directories to include in the package'
    )
    parser.add_argument('--version', required=True, help='Camoufox version')
    parser.add_argument('--release', required=True, help='Camoufox release number')
    parser.add_argument(
        '--arch', choices=['x86_64', 'i686', 'arm64'], help='Architecture for Windows build'
    )
    parser.add_argument('--fonts', nargs='+', help='Font directories to include under fonts/')
    return parser.parse_args()


def main():
    """The main packaging function"""
    args = get_args()

    # Determine file extension based on OS
    file_extensions = {'linux': 'tar.xz', 'macos': 'dmg', 'windows': 'zip'}
    file_ext = file_extensions[args.os]

    # Build the package
    src_dir = find_src_dir('.', args.version, args.release)
    moz_target = get_moz_target(target=args.os, arch=args.arch)
    with temp_cd(src_dir):
        # Create package files
        run('./mach package')
        # Find package files
        search_path = os.path.abspath(
            f'obj-{moz_target}/dist/camoufox-{args.version}-{args.release}.*.{file_ext}'
        )

    # Copy package files
    for file in glob.glob(search_path):
        if 'xpt_artifacts' in file:
            print(f'Skipping xpt artifacts: {file}')
            continue
        print(f'Found package: {file}')
        # Copy to root
        shutil.copy2(file, '.')
        break
    else:
        print(f"Error: No package file found matching pattern: {search_path}")
        sys.exit(1)

    # Find the package file
    package_pattern = f'camoufox-{args.version}-{args.release}.en-US.*.{file_ext}'
    package_files = glob.glob(package_pattern)
    if not package_files:
        print(f"Error: No package file found matching pattern: {package_pattern}")
        exit(1)
    package_file = package_files[0]

    # Add includes to the package
    new_name = f'camoufox-{args.version}-{args.release}-{args.os[:3]}.{args.arch}.zip'
    add_includes_to_package(
        package_file=package_file,
        includes=args.includes,
        fonts=args.fonts,
        new_file=new_name,
        target=args.os,
    )

    print(f"Packaging complete for {args.os}")


if __name__ == '__main__':
    main()
