#!/usr/bin/env python3

"""
Common functions used across the Camoufox build system.
Not meant to be called directly.
"""

import contextlib
import fnmatch
import optparse
import os
import re
import sys
import time

start_time = time.time()


@contextlib.contextmanager
def temp_cd(path):
    """Temporarily change to a different working directory"""
    _old_cwd = os.getcwd()
    abs_path = os.path.abspath(path)
    assert os.path.exists(abs_path), f'{abs_path} does not exist.'
    os.chdir(abs_path)

    try:
        yield
    finally:
        os.chdir(_old_cwd)


def get_options():
    """Get options"""
    parser = optparse.OptionParser()
    parser.add_option('--mozconfig-only', dest='mozconfig_only', default=False, action="store_true")
    return parser.parse_args()


def find_src_dir(root_dir='.', version=None, release=None):
    """Get the source directory"""
    if version and release:
        name = os.path.join(root_dir, f'camoufox-{version}-{release}')
        assert os.path.exists(name), f'{name} does not exist.'
        return name
    folders = os.listdir(root_dir)
    for folder in folders:
        if os.path.isdir(folder) and folder.startswith('camoufox-'):
            return os.path.join(root_dir, folder)
    raise FileNotFoundError('No camoufox-* folder found')


def get_moz_target(target, arch):
    """Get moz_target from target and arch"""
    if arch == "i686" and target != "windows":
        raise ValueError(f"Unsupported architecture for {target}: {arch}")
    if target == "linux":
        return "aarch64-unknown-linux-gnu" if arch == "arm64" else f"{arch}-pc-linux-gnu"
    if target == "windows":
        return f"{arch}-pc-windows-msvc"
    if target == "macos":
        return "aarch64-apple-darwin" if arch == "arm64" else f"{arch}-apple-darwin"
    raise ValueError(f"Unsupported target: {target}")


def mozilla_rust_version(src_dir):
    """The Rust release Mozilla builds this Firefox with: the toolchain its
    taskcluster aliases as linux64-rust. Its LLVM is the major version of the
    clang `mach bootstrap` fetches for the same tree, which cross-language LTO
    needs: lld cannot read Rust bitcode from a newer LLVM than its own."""
    path = os.path.join(src_dir, 'taskcluster', 'kinds', 'toolchain', 'rust.yml')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    versions = set()
    # One top-level entry per toolchain; the alias is either a plain value or
    # a by-project mapping whose default is the alias.
    for entry in re.split(r'^(?=\S)', text, flags=re.MULTILINE):
        if re.search(r'^\s+(?:toolchain-alias|default): linux64-rust$', entry, re.MULTILINE):
            versions.update(re.findall(r"'--channel', '(\d+\.\d+\.\d+)'", entry))
    if len(versions) != 1:
        raise ValueError(f'{path}: expected one Rust release aliased linux64-rust, '
                         f'found {sorted(versions) or "none"}')
    return versions.pop()


def list_files(root_dir, suffix):
    """List files in a directory"""
    for root, _, files in os.walk(root_dir):
        for file in fnmatch.filter(files, suffix):
            full_path = os.path.join(root, file)
            relative_path = os.path.relpath(full_path, root_dir)
            yield os.path.join(root_dir, relative_path).replace('\\', '/')


def list_patches(root_dir='../patches', suffix='*.patch'):
    """List all patch files"""
    return sorted(list_files(root_dir, suffix), key=os.path.basename)


def script_exit(statuscode):
    """Exit the script"""
    if (time.time() - start_time) > 60:
        # print elapsed time
        elapsed = time.strftime("%H:%M:%S", time.gmtime(time.time() - start_time))
        print(f"\n\aElapsed time: {elapsed}")
        sys.stdout.flush()

    sys.exit(statuscode)


def run(cmd, exit_on_fail=True, do_print=True):
    """Run a command"""
    if not cmd:
        return
    if do_print:
        print(cmd)
        sys.stdout.flush()
    retval = os.system(cmd)
    if retval != 0 and exit_on_fail:
        print(f"fatal error: command '{cmd}' failed")
        sys.stdout.flush()
        script_exit(1)
    return retval


__all__ = [
    'get_moz_target',
    'list_patches',
    'mozilla_rust_version',
    'run',
    'script_exit',
    'temp_cd',
    'get_options',
]


if __name__ == '__main__':
    print('This is a module, not meant to be called directly.')
    sys.exit(1)
