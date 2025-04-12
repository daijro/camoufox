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
run 'cp -v ../firefox/assets/search-config.json services/settings/dumps/main/search-config.json'

# vs_pack.py issue... should be temporary
run 'cp -v ../firefox/patches/librewolf/pack_vs.py build/vs/'

# Apply most recent `settings` repository files
run 'mkdir -p lw'
pushd lw > /dev/null
run 'cp -v ../../firefox/settings/camoufox.cfg .'
run 'cp -v ../../firefox/settings/distribution/policies.json .'
run 'cp -v ../../firefox/settings/defaults/pref/local-settings.js .'
run 'cp -v ../../firefox/settings/chrome.css .'
run 'cp -v ../../firefox/settings/properties.json .'
run 'touch moz.build'
popd > /dev/null

# Copy ALL new files/folders from ../firefox/additions to .
run 'cp -r ../firefox/additions/* .'

# Provide a script that fetches and bootstraps Nightly and some mozconfigs
run 'cp -v ../scripts/mozfetch.sh lw/'

# Override the firefox version
for file in "browser/config/version.txt" "browser/config/version_display.txt"; do
    echo "${version}-${release}" > "$file"
done
