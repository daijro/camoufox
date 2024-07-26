#!/bin/sh

set -e
echo "update-ubo-assets.sh"
echo

# Download the original assets.json from GitHub
echo "-> Downloading original assets.json"
assets=$(curl https://raw.githubusercontent.com/gorhill/uBlock/master/assets/assets.json)

# Overwrite the contentURL of assets.json so that uBO will always use the LW provided version
echo "-> Overwriting assets.json update location"
assets=$(echo "$assets" | jq '
  del(.["assets.json"].cdnURLs) | 
  .["assets.json"].contentURL = "https://gitlab.com/librewolf-community/browser/source/-/raw/main/assets/uBOAssets.json"
')

# Enable some filter lists that are disabled by default
function enable_filter_list {
  echo "-> Enabling filter list \"$1\""
  assets=$(echo "$assets" | jq "del(.[\"$1\"].off)")
}
enable_filter_list "curben-phishing"
enable_filter_list "adguard-spyware-url"

# Add some custom filter lists
function add_filter_list {
  echo "-> Adding custom filter list \"$1\""
  assets=$(echo "$assets" | jq ".[\"$1\"] = $2")
}
add_filter_list "LegitimateURLShortener" '{
  "content": "filters",
  "group": "privacy",
  "title": "➗ Actually Legitimate URL Shortener Tool",
  "contentURL": "https://raw.githubusercontent.com/DandelionSprout/adfilt/master/LegitimateURLShortener.txt",
  "supportURL": "https://github.com/DandelionSprout/adfilt/discussions/163"
}'
add_filter_list "bpc-paywall-filter" '{
  "content": "filters",
  "group": "annoyances",
  "title": "Bypass Paywalls Clean filter",
  "contentURL": "https://gitlab.com/magnolia1234/bypass-paywalls-clean-filters/-/raw/main/bpc-paywall-filter.txt",
  "supportURL": "https://gitlab.com/magnolia1234/bypass-paywalls-clean-filters"
}'
add_filter_list "AntiPaywall" '{
  "content": "filters",
  "group": "annoyances",
  "title": "Anti-paywall filters",
  "contentURL": "https://raw.githubusercontent.com/liamengland1/miscfilters/master/antipaywall.txt",
  "supportURL": "https://github.com/liamengland1/miscfilters"
}'

# Write the resulting json into line 4 of the patchfile
echo "-> Writing to assets/uBOAssets.json"
echo $assets | jq . >./assets/uBOAssets.json

git diff assets/uBOAssets.json

if [[ "$(
  read -e -p '-? Commit changes? [y/N] '
  echo $REPLY
)" == [Yy]* ]]; then
  echo "-> Committing changes"
  git add assets/uBOAssets.json
  git commit -m "Update uBOAssets.json with latest changes"
fi

echo
echo "Done!"
