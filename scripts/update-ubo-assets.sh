#!/bin/sh

set -e
echo "update-ubo-assets.sh"
echo

# Download the LibreWolf uBOAssets.json
echo "-> Downloading LibreWolf uBOAssets.json"
assets=$(curl https://gitlab.com/librewolf-community/browser/source/-/raw/main/assets/uBOAssets.json)

# Remove specified filter lists
echo "-> Removing specified filter lists"
assets=$(echo "$assets" | jq 'del(.["ublock-badware"], .["urlhaus-1"], .["curben-phishing"])')

# Write the resulting json
echo "-> Writing to assets/uBOAssets.json"
echo $assets | jq . >./assets/uBOAssets.json

echo
echo "Done!"