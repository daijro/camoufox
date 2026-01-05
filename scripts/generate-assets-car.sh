#!/bin/bash
# Generates Assets.car for macOS builds from the camoufox branding icons
# This script must be run on macOS (requires actool from Xcode)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANDING_DIR="$SCRIPT_DIR/../additions/browser/branding/camoufox"
XCASSETS_DIR="$BRANDING_DIR/Assets.xcassets"
APPICONSET_DIR="$XCASSETS_DIR/AppIcon.appiconset"
OUTPUT_FILE="$BRANDING_DIR/Assets.car"

# Check if running on macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo "Warning: Assets.car can only be generated on macOS."
    echo "Using existing Assets.car if available, or copying from official branding."

    # If Assets.car doesn't exist, try to copy from official branding
    if [[ ! -f "$OUTPUT_FILE" ]]; then
        OFFICIAL_ASSETS="$SCRIPT_DIR/../camoufox-*/browser/branding/official/Assets.car"
        if ls $OFFICIAL_ASSETS 1>/dev/null 2>&1; then
            cp $(ls $OFFICIAL_ASSETS | head -1) "$OUTPUT_FILE"
            echo "Copied Assets.car from official branding."
        else
            echo "Error: No Assets.car available and cannot generate on non-macOS."
            exit 1
        fi
    fi
    exit 0
fi

# Check for actool
if ! command -v actool &>/dev/null && ! xcrun --find actool &>/dev/null; then
    echo "Error: actool not found. Please install Xcode Command Line Tools."
    exit 1
fi

ACTOOL=$(xcrun --find actool 2>/dev/null || echo "actool")

echo "Generating Assets.car from camoufox branding icons..."

# Create xcassets structure
mkdir -p "$APPICONSET_DIR"

# Create Contents.json for the asset catalog
cat > "$XCASSETS_DIR/Contents.json" << 'EOF'
{
  "info" : {
    "author" : "xcode",
    "version" : 1
  }
}
EOF

# Create Contents.json for AppIcon with all icon sizes macOS needs
cat > "$APPICONSET_DIR/Contents.json" << 'EOF'
{
  "images" : [
    {
      "filename" : "icon_16x16.png",
      "idiom" : "mac",
      "scale" : "1x",
      "size" : "16x16"
    },
    {
      "filename" : "icon_16x16@2x.png",
      "idiom" : "mac",
      "scale" : "2x",
      "size" : "16x16"
    },
    {
      "filename" : "icon_32x32.png",
      "idiom" : "mac",
      "scale" : "1x",
      "size" : "32x32"
    },
    {
      "filename" : "icon_32x32@2x.png",
      "idiom" : "mac",
      "scale" : "2x",
      "size" : "32x32"
    },
    {
      "filename" : "icon_128x128.png",
      "idiom" : "mac",
      "scale" : "1x",
      "size" : "128x128"
    },
    {
      "filename" : "icon_128x128@2x.png",
      "idiom" : "mac",
      "scale" : "2x",
      "size" : "128x128"
    },
    {
      "filename" : "icon_256x256.png",
      "idiom" : "mac",
      "scale" : "1x",
      "size" : "256x256"
    },
    {
      "filename" : "icon_256x256@2x.png",
      "idiom" : "mac",
      "scale" : "2x",
      "size" : "256x256"
    },
    {
      "filename" : "icon_512x512.png",
      "idiom" : "mac",
      "scale" : "1x",
      "size" : "512x512"
    },
    {
      "filename" : "icon_512x512@2x.png",
      "idiom" : "mac",
      "scale" : "2x",
      "size" : "512x512"
    }
  ],
  "info" : {
    "author" : "xcode",
    "version" : 1
  }
}
EOF

# Copy/resize icons to the required sizes
# We'll use sips (macOS built-in) to resize if needed
copy_or_resize() {
    local src="$1"
    local dst="$2"
    local size="$3"

    if [[ -f "$src" ]]; then
        cp "$src" "$dst"
        sips -z "$size" "$size" "$dst" >/dev/null 2>&1 || true
    elif [[ -f "$BRANDING_DIR/default256.png" ]]; then
        # Fallback to default256 and resize
        cp "$BRANDING_DIR/default256.png" "$dst"
        sips -z "$size" "$size" "$dst" >/dev/null 2>&1 || true
    fi
}

# Map branding icons to xcassets icons
copy_or_resize "$BRANDING_DIR/default16.png" "$APPICONSET_DIR/icon_16x16.png" 16
copy_or_resize "$BRANDING_DIR/default32.png" "$APPICONSET_DIR/icon_16x16@2x.png" 32
copy_or_resize "$BRANDING_DIR/default32.png" "$APPICONSET_DIR/icon_32x32.png" 32
copy_or_resize "$BRANDING_DIR/default64.png" "$APPICONSET_DIR/icon_32x32@2x.png" 64
copy_or_resize "$BRANDING_DIR/default128.png" "$APPICONSET_DIR/icon_128x128.png" 128
copy_or_resize "$BRANDING_DIR/default256.png" "$APPICONSET_DIR/icon_128x128@2x.png" 256
copy_or_resize "$BRANDING_DIR/default256.png" "$APPICONSET_DIR/icon_256x256.png" 256
copy_or_resize "$BRANDING_DIR/default256.png" "$APPICONSET_DIR/icon_256x256@2x.png" 512
copy_or_resize "$BRANDING_DIR/default256.png" "$APPICONSET_DIR/icon_512x512.png" 512
copy_or_resize "$BRANDING_DIR/default256.png" "$APPICONSET_DIR/icon_512x512@2x.png" 1024

# Generate Assets.car using actool
TEMP_DIR=$(mktemp -d)
"$ACTOOL" \
    --compile "$TEMP_DIR" \
    --platform macosx \
    --minimum-deployment-target 10.15 \
    --app-icon AppIcon \
    --output-partial-info-plist "$TEMP_DIR/Info.plist" \
    "$XCASSETS_DIR"

# Move the generated Assets.car
if [[ -f "$TEMP_DIR/Assets.car" ]]; then
    mv "$TEMP_DIR/Assets.car" "$OUTPUT_FILE"
    echo "Successfully generated: $OUTPUT_FILE"
else
    echo "Error: Failed to generate Assets.car"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# Cleanup
rm -rf "$TEMP_DIR"

echo "Done!"
