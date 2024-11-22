#!/bin/bash

if [ $# -ne 2 ]; then
    echo "Usage: $0 <arch> <os>"
    echo "arch: x86_64, i686, arm64"
    echo "os: linux, windows, macos"
    exit 1
fi

ARCH=$1
OS=$2

case $ARCH in
    x86_64) GOARCH=amd64 ;;
    i686)   GOARCH=386 ;;
    arm64)  GOARCH=arm64 ;;
    *)      echo "Invalid architecture"; exit 1 ;;
esac

case $OS in
    linux)   GOOS=linux ;;
    windows) GOOS=windows ;;
    macos)   GOOS=darwin ;;
    *)       echo "Invalid OS"; exit 1 ;;
esac

[ "$OS" = "windows" ] && OUTPUT="launch.exe" || OUTPUT="launch"

rm -rf ./dist launch launch.exe

echo Building launcher...
GOOS=$GOOS GOARCH=$GOARCH go build -o dist/$OUTPUT || exit 1

echo "Complete: launcher/dist/$OUTPUT"