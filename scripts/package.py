#!/usr/bin/env python3

import argparse
import glob
import hashlib
import json
import os
import shutil
import sys
import tempfile
from shlex import join

from _mixin import find_src_dir, get_moz_target, list_files, run, temp_cd

# The GPU probe is NOT here (gfxtest; glxtest and vaapitest before Firefox 156):
# Firefox runs it at startup to learn what the GPU and the video stack can do,
# and without it nsIGfxInfo has no data, so the driver blocklist refuses every
# WebGL context ("WebglAllowWindowsNativeGl:
# false restricts context creation on this system ... Exhausted GL driver
# options", measured 2026-09-18 against stock 152.0.4 on the same machine, which
# returned a full WebGL 2.0 context from the real GPU). The launcher papers over
# it with webgl.force-enabled; shipping the probe is what makes the browser
# decide the way stock does in the first place. ~50 KB.
UNNEEDED_PATHS = {'uninstall', 'pingsender.exe', 'pingsender'}


def inject_locales(target_dir, target, version, src_dir):
    """Bake the official language packs in as packaged locales.

    Without them a spoofed non-English locale localizes Intl/number/date
    formatting but leaves every browser-provided string that content can read
    (input.validationMessage, XML parse errors) in English -- a mix no real
    Firefox produces. A langpack add-on does not fix it: the parent pre-creates
    those string bundles before add-ons start. Packaged locales are what a
    Mozilla localized build has, selected by intl.locale.requested (pythonlib).
    """
    langpacks = os.path.join('bundle', 'langpacks')
    version_file = os.path.join(langpacks, 'VERSION')
    base_version = version.split('-')[0]
    have = open(version_file).read().strip() if os.path.exists(version_file) else None
    if have != base_version:
        # Not in git (bundle/langpacks is ignored): fetch them from
        # archive.mozilla.org the way `make fetch` fetches the source.
        run(join([sys.executable, os.path.join('scripts', 'fetch-langpacks.py'), base_version]))
        have = open(version_file).read().strip() if os.path.exists(version_file) else None
    if have != base_version:
        raise FileNotFoundError(
            f"bundle/langpacks is for Firefox {have}, need {base_version}: "
            f"run scripts/fetch-langpacks.py {base_version}"
        )
    # Mozilla's macOS Japanese build is ja-JP-mac; every other platform ships ja.
    skip = 'ja' if target == 'macos' else 'ja-JP-mac'
    xpis = sorted(
        path for path in glob.glob(os.path.join(langpacks, '*.xpi'))
        if os.path.basename(path)[:-4] != skip
    )
    run(join([sys.executable, os.path.join('scripts', 'inject-locales.py'),
              '--source-tree', src_dir, target_dir, *xpis]))



def font_groups_for(groups_file, oses):
    """Group directories the named OSes read, or None if the bundle predates groups."""
    if not os.path.exists(groups_file):
        return None
    with open(groups_file, encoding='utf-8') as fh:
        read_by = json.load(fh).get('readBy', {})
    key = {'linux': 'lin', 'macos': 'mac', 'windows': 'win'}
    out = set()
    for o in oses:
        out.update(read_by.get(key.get(o, o), []))
    return sorted(out)


def legacy_font_copy(target, fonts, fonts_dir):
    """The pre-groups layout: one full copy of each OS's set under fonts/<os>/."""
    if target == 'linux':
        for font in fonts or []:
            shutil.copytree(os.path.join('bundle', 'fonts', font),
                            os.path.join(fonts_dir, font), dirs_exist_ok=True)
    else:
        os.makedirs(fonts_dir, exist_ok=True)
        for font in fonts or []:
            for file in list_files(root_dir=os.path.join('bundle', 'fonts', font), suffix='*'):
                shutil.copy2(file, os.path.join(fonts_dir, os.path.basename(file)))


def add_includes_to_package(package_file, includes, fonts, new_file, target, version, src_dir):
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
                version=version,
                src_dir=src_dir,
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

        # Add includes.
        #
        # A missing entry is fatal rather than skipped: the Windows package pulls
        # the MSVC CRT in through a shell glob, and when that glob does not
        # expand (different toolchain version on the build host) the literal
        # pattern used to be silently ignored -- shipping a browser that cannot
        # start on any machine without the redistributable installed.
        missing = [include for include in includes or [] if not os.path.exists(include)]
        if missing:
            raise FileNotFoundError(
                "Missing --includes entries (unexpanded glob or wrong path):\n  "
                + "\n  ".join(missing)
            )

        for include in includes or []:
            if os.path.isdir(include):
                shutil.copytree(
                    include,
                    os.path.join(target_dir, os.path.basename(include)),
                    dirs_exist_ok=True,
                )
            else:
                shutil.copy2(include, target_dir)

        # Add the fonts under fonts/.
        #
        # The bundle stores each face ONCE, in a directory named for the set of
        # OSes that use it (L, M, W, LM, LW, MW, LMW -- bundle/fonts/groups.json).
        # Storing a copy per OS instead made 41% of the bundle byte-identical
        # duplicates. `fonts` still names OSes; the groups each one reads are
        # looked up here, so the set a package ships is unchanged.
        fonts_dir = os.path.join(target_dir, 'fonts')
        groups_file = os.path.join('bundle', 'fonts', 'groups.json')
        wanted = font_groups_for(groups_file, fonts or [])
        if wanted is None:
            legacy_font_copy(target, fonts, fonts_dir)
        elif target == 'linux':
            # Linux resolves fonts through fontconfig, which is handed the exact
            # group directories for the claimed OS at launch (utils._generate_fontconfig),
            # so the subdirectories are the per-OS gate and must be preserved.
            for g in wanted:
                shutil.copytree(os.path.join('bundle', 'fonts', g),
                                os.path.join(fonts_dir, g), dirs_exist_ok=True)
            shutil.copy2(groups_file, os.path.join(fonts_dir, 'groups.json'))
        else:
            # macOS (CoreText) and Windows (DirectWrite) activate ONE flat
            # directory and cannot read subfolders, so there is no directory
            # gate on those targets -- the font allowlist is what restricts a
            # lookup (font-hijacker.patch). Flatten, skipping any face whose
            # bytes are already present.
            os.makedirs(fonts_dir, exist_ok=True)
            seen = set()
            for g in wanted:
                for file in list_files(root_dir=os.path.join('bundle', 'fonts', g), suffix='*'):
                    with open(file, 'rb') as fh:
                        digest = hashlib.sha256(fh.read()).hexdigest()
                    if digest in seen:
                        continue
                    seen.add(digest)
                    shutil.copy2(file, os.path.join(fonts_dir, os.path.basename(file)))

        inject_locales(target_dir, target, version, src_dir)

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
        version=args.version,
        src_dir=os.path.abspath(src_dir),
    )

    print(f"Packaging complete for {args.os}")


if __name__ == '__main__':
    main()
