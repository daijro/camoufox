#!/usr/bin/env bash

# resources:
# https://www.talospace.com/2021/12/firefox-95-on-power.html

distro=linux
#distro=macos


# ac_add_options --with-wasi-sysroot=$HOME/.mozbuild/wrlb/wasi-sysroot
target_wasi_location=$HOME/.mozbuild/wrlb/

set -e

# taken from: https://github.com/WebAssembly/wasi-sdk/
export WASI_VERSION=14
export WASI_VERSION_FULL=${WASI_VERSION}.0

# cleanup first..
rm -f wasi-sdk-${WASI_VERSION_FULL}-$distro.tar.gz*
rm -rf wasi-sdk-${WASI_VERSION_FULL}

wget https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-${WASI_VERSION}/wasi-sdk-${WASI_VERSION_FULL}-$distro.tar.gz
tar xvf wasi-sdk-${WASI_VERSION_FULL}-$distro.tar.gz


# taken from macos: https://gitlab.com/librewolf-community/browser/macos/-/blob/master/build.sh#L109
if [[ "$distro" == "macos" ]]; then
    wasi_path=/usr/local/Cellar/llvm/13.0.0_2/lib/clang/13.0.0/lib
    mkdir $HOME/.mozbuild/wrlb
    mkdir $wasi_path/wasi
    cp -r wasi-sdk-14.0/share/wasi-sysroot $HOME/.mozbuild/wrlb/wasi-sysroot
    cp -v wasi-sdk-14.0/lib/clang/13.0.0/lib/wasi/libclang_rt.builtins-wasm32.a $wasi_path/wasi/
elif [[ "$distro" == "linux" ]]; then
     mkdir -p $target_wasi_location
     rm -rf $target_wasi_location/wasi-sysroot
     cp -vr wasi-sdk-14.0/share/wasi-sysroot $target_wasi_location

     rm -f wasi-sdk-${WASI_VERSION_FULL}-$distro.tar.gz*
     rm -rf wasi-sdk-${WASI_VERSION_FULL}
fi
