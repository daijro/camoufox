#!/usr/bin/env python3

"""
Check that a target builds, without building it: configure, run the export
tiers, then compile the object of every source file a patch or an addition
touches. Linking and packaging are left to a full build.

Run:
    python3 scripts/preflight.py <source dir>
"""

import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from _mixin import run, temp_cd

SOURCE_SUFFIXES = {'.c', '.cc', '.cpp', '.m', '.mm', '.S', '.s', '.asm'}


def touched_sources(browser):
    """Every compiled file a patch changes or an addition provides, relative to the tree"""
    touched = {str(f.relative_to(browser / 'additions'))
               for f in (browser / 'additions').rglob('*') if f.is_file()}
    for patch in (browser / 'patches').rglob('*.patch'):
        touched.update(re.findall(r'^\+\+\+ b/(\S+)', patch.read_text(encoding='utf-8', errors='replace'), re.M))
    return {path for path in touched if Path(path).suffix in SOURCE_SUFFIXES}


def objects_of(touched, tree, objdir):
    """{objdir directory: its objects that hold a touched source}, and the sources this target builds"""
    suffix = re.search(r'^OBJ_SUFFIX = (\S+)', (objdir / 'config' / 'autoconf.mk').read_text(), re.M).group(1)
    objects, built = defaultdict(set), set()

    def record(source, directory, name):
        source = os.path.relpath(os.path.normpath(source), tree)
        if source in touched:
            objects[directory].add(f'{Path(name).stem}.{suffix}')
            built.add(source)

    # A unified source includes the files it stands for
    for unified in objdir.rglob('Unified_*'):
        if unified.suffix in SOURCE_SUFFIXES:
            for included in re.findall(r'^#include "([^"]+)"', unified.read_text(errors='replace'), re.M):
                record(unified.parent / included, unified.parent, unified.name)
    for backend in objdir.rglob('backend.mk'):
        makefile = (backend.parent / 'Makefile').read_text()
        srcdir = tree / re.search(r'^relativesrcdir := (\S+)', makefile, re.M).group(1)
        for source in re.findall(r'^\w*(?:SRCS|ASFILES) \+= (\S+)', backend.read_text(errors='replace'), re.M):
            source = source.replace('$(srcdir)', str(srcdir)).replace('$(topsrcdir)', str(tree))
            record(backend.parent / source, backend.parent, source)
    return objects, built


def compile_objects(objects, objdir):
    """Compile them under one make, so its job server shares the cores between directories"""
    # make does not load an object's header dependencies when the object is
    # the goal, so one left by an earlier run would pass without compiling.
    for directory, names in objects.items():
        for name in names:
            (directory / name).unlink(missing_ok=True)
    rules = [f'{n}:\n\t+$(MAKE) -C {directory} {" ".join(sorted(names))}\n'
             for n, (directory, names) in enumerate(sorted(objects.items()))]
    wrapper = objdir / 'preflight.mk'
    targets = ' '.join(str(n) for n in range(len(rules)))
    wrapper.write_text(f'.PHONY: all {targets}\nall: {targets}\n' + ''.join(rules))
    run(f'make -f {wrapper} -k -j{os.cpu_count()} --output-sync=target')


if __name__ == '__main__':
    browser = Path.cwd()
    tree = (browser / sys.argv[1]).resolve()
    with temp_cd(tree):
        run('./mach configure')
        # pre-compile generates the last headers the objects include
        run('./mach build pre-export export pre-compile')
        objdir = Path(json.loads(subprocess.check_output(['./mach', 'environment', '--format=json']))['topobjdir'])
        touched = touched_sources(browser)
        objects, built = objects_of(touched, tree, objdir)
        print(f'{len(touched)} sources are patched or added; this target builds {len(built)} of them, '
              f'in {sum(map(len, objects.values()))} objects')
        if not objects:
            sys.exit(f'error: found no object for a patched source in {objdir}')
        compile_objects(objects, objdir)
