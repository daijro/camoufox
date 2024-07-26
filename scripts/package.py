#!/usr/bin/env python3

import argparse
import glob
import os
import shutil
import subprocess
import tempfile

UNNEEDED_PATHS = {'uninstall', 'pingsender.exe', 'pingsender', 'vaapitest', 'glxtest'}


def run_command(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error executing command: {' '.join(command)}")
        print(f"Error output: {result.stderr}")
        exit(1)
    return result.stdout


def add_includes_to_package(package_file, includes, fonts, new_file, os):
    with tempfile.TemporaryDirectory() as temp_dir:
        # Extract package
        run_command(['7z', 'x', package_file, f'-o{temp_dir}'])
        # Delete package_file
        os.remove(package_file)
        if package_file.endswith('.tar.bz2'):
            # Rerun on the tar file
            package_tar = package_file[:-4]  # Remove .bz2
            return add_includes_to_package(
                package_file=os.path.join(temp_dir, package_tar),
                includes=includes,
                fonts=fonts,
                new_file=new_file,
                os=os,
            )

        if os == 'macos':
            # Move Nightly/Nightly.app -> Camoufox.app
            nightly_dir = os.path.join(temp_dir, 'Nightly')
            shutil.move(
                os.path.join(nightly_dir, 'Nightly.app'), os.path.join(temp_dir, 'Camoufox.app')
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
        if os == 'macos':
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

        # Add fonts under fonts/
        for font in fonts or []:
            shutil.copytree(
                os.path.join('bundle', 'fonts', font),
                os.path.join(target_dir, 'fonts', font),
                dirs_exist_ok=True,
            )

        # Add launcher from launcher/dist/launch to temp_dir
        shutil.copy2(
            os.path.join('launcher', 'dist', 'launch'),
            os.path.join(temp_dir, 'launch' + ('.exe' if os == 'windows' else '')),
        )

        # Remove unneeded paths
        for path in UNNEEDED_PATHS:
            if os.path.isdir(os.path.join(target_dir, path)):
                shutil.rmtree(os.path.join(target_dir, path), ignore_errors=True)
            elif os.path.exists(os.path.join(target_dir, path)):
                os.remove(os.path.join(target_dir, path))

        # Update package
        run_command(['7z', 'u', new_file, f'{temp_dir}/*', '-r', '-mx=9'])


def main():
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
        '--arch', choices=['x64', 'x86', 'arm64'], help='Architecture for Windows build'
    )
    parser.add_argument('--fonts', nargs='+', help='Font directories to include under fonts/')
    args = parser.parse_args()

    # Determine file extension based on OS
    file_extensions = {'linux': 'tar.bz2', 'macos': 'dmg', 'windows': 'zip'}
    file_ext = file_extensions[args.os]

    # Remove xpt_artifacts file if it exists
    xpt_artifacts_pattern = f'camoufox-{args.version}-{args.release}.*.xpt_artifacts.*'
    for xpt_file in glob.glob(xpt_artifacts_pattern):
        if os.path.exists(xpt_file):
            os.remove(xpt_file)

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
        os==args.os,
    )

    print(f"Packaging complete for {args.os}")


if __name__ == '__main__':
    main()
