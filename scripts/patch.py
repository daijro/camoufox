#!/usr/bin/env python3

"""
The script that patches the firefox source into the camoufox source.
"""

import fnmatch
import hashlib
import optparse
import os
import shutil
import sys
import time

start_time = time.time()
parser = optparse.OptionParser()
parser.add_option('-n', '--no-execute', dest='no_execute', default=False, action="store_true")
parser.add_option(
    '-P', '--no-settings-pane', dest='settings_pane', default=True, action="store_false"
)
options, args = parser.parse_args()

"""
Helper functions
"""


def script_exit(statuscode):
    if (time.time() - start_time) > 60:
        # print elapsed time
        elapsed = time.strftime("%H:%M:%S", time.gmtime(time.time() - start_time))
        print(f"\n\aElapsed time: {elapsed}")
        sys.stdout.flush()

    sys.exit(statuscode)


def run(cmd, exit_on_fail=True, do_print=True):
    if not cmd:
        return
    if do_print:
        print(cmd)
        sys.stdout.flush()
    if options.no_execute:
        return None
    retval = os.system(cmd)
    if retval != 0 and exit_on_fail:
        print(f"fatal error: command '{cmd}' failed")
        sys.stdout.flush()
        script_exit(1)
    return retval


def patch(patchfile, reverse=False):
    if reverse:
        cmd = f"patch -p1 -R -i {patchfile}"
    else:
        cmd = f"patch -p1 -i {patchfile}"
    print(f"\n*** -> {cmd}")
    sys.stdout.flush()
    if options.no_execute:
        return
    retval = os.system(cmd)
    if retval != 0:
        print(f"fatal error: patch '{patchfile}' failed")
        sys.stdout.flush()
        script_exit(1)


def enter_srcdir(_dir=None):
    if _dir is None:
        dir = f"camoufox-{version}-{release}"
    else:
        dir = _dir
    print(f"cd {dir}")
    sys.stdout.flush()
    if options.no_execute:
        return
    try:
        os.chdir(dir)
    except:
        print(f"fatal error: can't change to '{dir}' folder.")
        sys.stdout.flush()
        script_exit(1)


def leave_srcdir():
    print("cd ..")
    sys.stdout.flush()
    if not options.no_execute:
        os.chdir("..")


def list_files(root_dir, suffix='*.patch'):
    for root, _, files in os.walk(root_dir):
        for file in fnmatch.filter(files, suffix):
            full_path = os.path.join(root, file)
            relative_path = os.path.relpath(full_path, root_dir)
            yield os.path.join('..', 'patches', relative_path).replace('\\', '/')


def add_rustup(*targets):
    for rust_target in targets:
        os.system(f'~/.cargo/bin/rustup target add "{rust_target}"')


"""
Main patcher function
"""


def camoufox_patches():
    enter_srcdir()

    # Create the right mozconfig file
    run('cp -v ../assets/base.mozconfig mozconfig')
    # Set cross building
    print(f'Using target: {moz_target}')
    _update_mozconfig()

    # Copy the search-config.json file
    run('cp -v ../assets/search-config.json services/settings/dumps/main/search-config.json')

    # Apply bootstraps first
    for patch_file in list_files('../patches', suffix='*.bootstrap'):
        patch(patch_file)
    # Then apply all other patches
    for patch_file in list_files('../patches'):
        patch(patch_file)

    # vs_pack.py issue... should be temporary
    run('cp -v ../patches/librewolf/pack_vs.py build/vs/')

    """
    Apply most recent `settings` repository files.
    """

    run('mkdir -p lw', exit_on_fail=False)
    enter_srcdir('lw')
    run('cp -v ../../settings/camoufox.cfg .')
    run('cp -v ../../settings/distribution/policies.json .')
    run('cp -v ../../settings/defaults/pref/local-settings.js .')
    run('cp -v ../../settings/chrome.css .')
    leave_srcdir()

    # Copy ALL new files/folders from ../additions to .
    run('cp -r ../additions/* .')

    # Provide a script that fetches and bootstraps Nightly and some mozconfigs
    run('cp -v ../scripts/mozfetch.sh lw/')

    # Override the firefox version
    for file in ["browser/config/version.txt", "browser/config/version_display.txt"]:
        with open(file, "w") as f:
            f.write(f"{version}-{release}")

    # Generate locales
    run("bash ../scripts/generate-locales.sh")

    leave_srcdir()


"""
Helpers for adding additional mozconfig code from assets/<target>.mozconfig
"""


def _get_moz_target():
    if target == "linux":
        return "aarch64-unknown-linux-gnu" if arch == "arm64" else f"{arch}-pc-linux-gnu"
    if target == "windows":
        return f"{arch}-pc-mingw32"
    if target == "macos":
        return "aarch64-apple-darwin" if arch == "arm64" else f"{arch}-apple-darwin"
    raise ValueError(f"Unsupported target: {target}")


def _update_rustup(target):
    if target == "linux":
        add_rustup("aarch64-unknown-linux-gnu", "i686-unknown-linux-gnu")
    elif target == "windows":
        add_rustup("x86_64-pc-windows-msvc", "aarch64-pc-windows-msvc", "i686-pc-windows-msvc")
    elif target == "macos":
        add_rustup("x86_64-apple-darwin", "aarch64-apple-darwin")


def _update_mozconfig():
    mozconfig_backup = "mozconfig.backup"
    mozconfig = "mozconfig"
    mozconfig_hash = "mozconfig.hash"

    # Create backup if it doesn't exist
    if not os.path.exists(mozconfig_backup):
        if os.path.exists(mozconfig):
            shutil.copy2(mozconfig, mozconfig_backup)
        else:
            with open(mozconfig_backup, 'w') as f:
                pass

    # Read backup content
    with open(mozconfig_backup, 'r') as f:
        content = f.read()

    # Add target option
    content += f"\nac_add_options --target={moz_target}\n"

    # Add target-specific mozconfig if it exists
    target_mozconfig = os.path.join("..", "assets", f"{target}.mozconfig")
    if os.path.exists(target_mozconfig):
        with open(target_mozconfig, 'r') as f:
            content += f.read()

    # Add macOS-specific hack
    # if target == "macos" and arch == "x86_64":
    #     content += 'export NASM="$MOZBUILD/nasm/nasm"\n'

    # Calculate new hash
    new_hash = hashlib.sha256(content.encode()).hexdigest()

    # Read old hash
    old_hash = ''
    if os.path.exists(mozconfig_hash):
        with open(mozconfig_hash, 'r') as f:
            old_hash = f.read().strip()

    # Update mozconfig if hash changed
    if new_hash != old_hash:
        print(f"-> Updating mozconfig, target is {moz_target}")
        with open(mozconfig, 'w') as f:
            f.write(content)
        with open(mozconfig_hash, 'w') as f:
            f.write(new_hash)
        return True
    return False


"""
Preparation
"""

if __name__ == "__main__":
    # Extract args
    if len(args) != 2:
        sys.stderr.write('error: please specify version and release of camoufox source')
        sys.exit(1)
    version, release = args[0], args[1]

    # Get moz_target if passed to BUILD_TARGET environment variable
    AVAILABLE_TARGETS = ["linux", "windows", "macos"]
    AVAILABLE_ARCHS = ["x86_64", "arm64", "i686"]

    if os.environ.get('BUILD_TARGET'):
        target, arch = os.environ['BUILD_TARGET'].split(',')
        assert target in AVAILABLE_TARGETS, f"Unsupported target: {target}"
        assert arch in AVAILABLE_ARCHS, f"Unsupported architecture: {arch}"
    else:
        target, arch = "linux", "x86_64"
    moz_target = _get_moz_target()
    _update_rustup(target=target)

    # Check if the folder exists
    if not os.path.exists(f'camoufox-{version}-{release}/configure.py'):
        sys.stderr.write('error: folder doesn\'t look like a Firefox folder.')
        sys.exit(1)

    # Apply the patches
    camoufox_patches()

    sys.exit(0)  # ensure 0 exit code
