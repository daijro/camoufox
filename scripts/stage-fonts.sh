#!/bin/bash
# Stage the bundled fonts and fontconfig into a local build's dist/bin.
#
# `mach build` leaves dist/bin/fonts holding only TwemojiMozilla.ttf; the font
# bundles and fontconfig are staged by scripts/package.py, so they exist only in
# packaged builds. Anything that runs the objdir binary directly -- `make run`,
# `make tests`, build-tester -- therefore starts a browser with no usable
# content font, and every glyph renders as a tofu box. That is silent: the
# browser chrome still has system fonts, so only page content is affected.
#
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

for dir in linux macos windows; do
    if [ ! -d "$dist_bin/fonts/$dir" ]; then
        mkdir -p "$dist_bin/fonts"
        cp -r "$repo_root/bundle/fonts/$dir" "$dist_bin/fonts/"
        echo "staged fonts/$dir"
    fi
    if [ ! -d "$dist_bin/fontconfig/$dir" ]; then
        mkdir -p "$dist_bin/fontconfig"
        cp -r "$repo_root/bundle/fontconfig/$dir" "$dist_bin/fontconfig/"
        echo "staged fontconfig/$dir"
    fi
done
