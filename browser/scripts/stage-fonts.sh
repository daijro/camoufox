#!/bin/bash
# Stage the bundled fonts and fontconfig into a local build's dist/bin.
#
# Only scripts/package.py stages them, so an objdir binary renders page content
# as tofu, silently. The bundle's group directories (bundle/fonts/groups.json)
# are staged verbatim so the launcher's per-OS font gate works here too.
# Idempotent, and cheap enough to run before every launch.

set -e

version="$1"
release="$2"
if [ -z "$version" ] || [ -z "$release" ]; then
    echo "Usage: $0 <version> <release>" >&2
    exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dist_bin="$repo_root/camoufox-$version-$release/obj-x86_64-pc-linux-gnu/dist/bin"

if [ ! -d "$dist_bin" ]; then
    exit 0  # nothing built yet
fi

# The bundle is a release asset rather than repo content, so a fresh checkout
# has no bundle/fonts/ at all. Say so with the command that fixes it instead of
# failing inside cp. (The Makefile target depends on fonts-extract, so reaching
# this means the script was run directly.)
bundle_fonts="$repo_root/bundle/fonts"
if [ ! -f "$bundle_fonts/groups.json" ]; then
    echo "no font bundle at bundle/fonts/ -- run: make fonts-extract" >&2
    exit 1
fi

if [ ! -f "$dist_bin/fonts/groups.json" ]; then
    mkdir -p "$dist_bin/fonts"
    # By name, not a wildcard: bundle/fonts/ also holds fetch-fonts.py's
    # .bundle-sha256 bookkeeping file, which has no business in a browser's font
    # directory. groups.json goes last, so an interrupted copy leaves no marker
    # and the next run stages again instead of trusting a partial tree.
    read -r -a groups <<<"$(python3 -c \
        'import json,sys; print(" ".join(json.load(open(sys.argv[1]))["groups"]))' \
        "$bundle_fonts/groups.json")"
    for g in "${groups[@]}"; do
        cp -r "$bundle_fonts/$g" "$dist_bin/fonts/"
    done
    cp "$bundle_fonts/groups.json" "$dist_bin/fonts/groups.json"
    echo "staged fonts/ (${#groups[@]} groups)"
fi

for dir in linux macos windows; do
    if [ ! -d "$dist_bin/fontconfig/$dir" ]; then
        mkdir -p "$dist_bin/fontconfig"
        cp -r "$repo_root/bundle/fontconfig/$dir" "$dist_bin/fontconfig/"
        echo "staged fontconfig/$dir"
    fi
done
