#!/bin/bash

# Simple bash script that copies the additions from the repository into the source directory
# Must be ran from within the source directory

# Check if correct number of arguments are provided
if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <version> <release>"
    exit 1
fi

# Assign command-line arguments to variables
version="$1"
release="$2"

# Function to run commands and exit on failure
run() {
    echo "$ $1"
    eval "$1"
    if [ $? -ne 0 ]; then
        echo "Command failed: $1"
        exit 1
    fi
}

# Copy the search-config.json file
run 'cp -v ../assets/search-config.json services/settings/dumps/main/search-config.json'

# vs_pack.py issue... should be temporary
run 'cp -v ../patches/librewolf/pack_vs.py build/vs/'

# Apply most recent `settings` repository files
run 'mkdir -p lw'
pushd lw > /dev/null
run 'cp -v ../../settings/camoufox.cfg .'
run 'cp -v ../../settings/distribution/policies.json .'
run 'cp -v ../../settings/defaults/pref/local-settings.js .'
run 'cp -v ../../settings/chrome.css .'
run 'cp -v ../../settings/properties.json .'
run 'touch moz.build'
popd > /dev/null

# Generate Assets.car for macOS builds (if on macOS) or ensure it exists
if [[ ! -f ../additions/browser/branding/camoufox/Assets.car ]]; then
    echo "Generating Assets.car..."
    bash ../scripts/generate-assets-car.sh
fi

# Copy ALL new files/folders from ../additions to .
run 'cp -r ../additions/* .'

# Provide a script that fetches and bootstraps Nightly and some mozconfigs
run 'cp -v ../scripts/mozfetch.sh lw/'

# Override the firefox version
for file in "browser/config/version.txt" "browser/config/version_display.txt"; do
    echo "${version}-${release}" > "$file"
done
