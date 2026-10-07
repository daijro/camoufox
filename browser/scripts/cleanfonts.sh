#!/bin/bash

# Simple bash script to reencode the font with fontforge
# Usage: <script> <fonts path>

# Path to the directory containing font files
FONT_DIR="$1"

# FontForge script to open and generate a new font file
FONTFORGE_SCRIPT=$(cat << 'EOF'
Open($1)
Generate($2)
Close()
EOF
)

# Loop through all .ttf and .otf files in the directory
for INPUT_FONT in "$FONT_DIR"/*.{ttf,otf}; do
    # Check if the file exists to avoid errors if no .ttf or .otf files are found
    if [[ -f "$INPUT_FONT" ]]; then
        # Determine the output file name
        OUTPUT_FONT="${INPUT_FONT%.*}_cleaned.${INPUT_FONT##*.}"

        # Run the FontForge script
        fontforge -lang=ff -c "$FONTFORGE_SCRIPT" "$INPUT_FONT" "$OUTPUT_FONT"

        echo "Cleaned font generated: $OUTPUT_FONT"
    fi
done
