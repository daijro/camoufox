"""browser/scripts/preflight.py: which objects hold the sources a patch or an addition touches."""

import sys

from ci._util import BROWSER_ROOT

sys.path.insert(0, str(BROWSER_ROOT / "scripts"))
from preflight import compile_objects, objects_of, touched_sources  # noqa: E402


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_touched_sources_are_the_compiled_files_of_patches_and_additions(tmp_path):
    _write(tmp_path / "patches" / "a.patch",
           "--- a/dom/base/Patched.cpp\n+++ b/dom/base/Patched.cpp\n@@ -1 +1 @@\n"
           "--- a/dom/base/Patched.h\n+++ b/dom/base/Patched.h\n@@ -1 +1 @@\n")
    _write(tmp_path / "patches" / "playwright" / "b.patch", "+++ b/widget/cocoa/Keys.mm\n")
    _write(tmp_path / "additions" / "camoucfg" / "Added.cpp")
    _write(tmp_path / "additions" / "camoucfg" / "moz.build")
    assert touched_sources(tmp_path) == {"dom/base/Patched.cpp", "widget/cocoa/Keys.mm", "camoucfg/Added.cpp"}


def test_objects_are_read_from_what_the_target_builds(tmp_path):
    tree = tmp_path / "tree"
    objdir = tree / "obj"
    _write(objdir / "config" / "autoconf.mk", "CC = clang\nOBJ_SUFFIX = obj\n")
    # A unified source, and a file built on its own beside it.
    _write(objdir / "dom" / "base" / "Makefile", "relativesrcdir := dom/base\n")
    _write(objdir / "dom" / "base" / "backend.mk",
           "CPPSRCS += $(srcdir)/Alone.cpp\nUNIFIED_CPPSRCS := Unified_cpp_dom_base0.cpp\n")
    _write(objdir / "dom" / "base" / "Unified_cpp_dom_base0.cpp",
           '#define MOZ_UNIFIED_BUILD\n#include "../../../dom/base/Patched.cpp"\n#include "../../../dom/base/Other.cpp"\n')
    # A gyp directory: its objects sit a level below its sources.
    _write(objdir / "media" / "lib" / "lib_lib" / "Makefile", "relativesrcdir := media/lib\n")
    _write(objdir / "media" / "lib" / "lib_lib" / "backend.mk", "CSRCS += $(srcdir)/src/codec.c\n")

    touched = {"dom/base/Patched.cpp", "dom/base/Alone.cpp", "media/lib/src/codec.c", "widget/cocoa/Keys.mm"}
    objects, built = objects_of(touched, tree, objdir)
    assert objects == {
        objdir / "dom" / "base": {"Unified_cpp_dom_base0.obj", "Alone.obj"},
        objdir / "media" / "lib" / "lib_lib": {"codec.obj"},
    }
    # Keys.mm is not part of this target, so nothing is compiled for it.
    assert built == touched - {"widget/cocoa/Keys.mm"}


def test_an_object_from_an_earlier_run_is_compiled_again(tmp_path):
    """make does not load an object's header dependencies when the object is
    the goal: with the release's broken header in place, a second preflight
    in the same tree found every object up to date and passed."""
    directory = tmp_path / "gfx"
    _write(directory / "Makefile", "%.o:\n\techo compiled > $@\n")
    _write(directory / "Stale.o", "left by an earlier run\n")
    compile_objects({directory: {"Stale.o", "New.o"}}, tmp_path)
    assert (directory / "Stale.o").read_text() == "compiled\n"
    assert (directory / "New.o").read_text() == "compiled\n"
