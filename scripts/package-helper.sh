#!/bin/bash

# package_helper.sh
add_includes_to_package() {
    echo "Adding includes to package: $1"
    temp_dir=$(mktemp -d)
    7z x "$1" "-o$temp_dir"
    if [ -d "$temp_dir/camoufox" ]; then
        mv "$temp_dir/camoufox"/* "$temp_dir/"
        rmdir "$temp_dir/camoufox"
    fi
    for include in "${@:2}"; do
        if [ -e "$include" ]; then
            cp -r "$include" "$temp_dir/"
        fi
    done
    (cd "$temp_dir" && 7z u "../$1" ./* -r -tzip -mx=9)
    rm -rf "$temp_dir"
}

# Execute the function with all arguments passed to the script
add_includes_to_package "$@"