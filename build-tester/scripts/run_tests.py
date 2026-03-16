#!/usr/bin/env python3
"""
Camoufox Build Tester — Python CLI

Runs the same antibot-detection checks as the Next.js web app,
but as a standalone CLI with ASCII art certificate output.

Usage:
  python scripts/run_tests.py <binary_path> [options]

Options:
  --profile-count N     Number of profiles to test (1-8, default: 8)
  --secret KEY          HMAC signing key for certificate
  --save-cert PATH      Save certificate text to this file
  --no-cert             Skip certificate generation
"""

import argparse
import asyncio
import os
import sys

from runner import run_tests


def main():
    parser = argparse.ArgumentParser(
        description="Camoufox Build Tester — runs antibot-detection checks via Playwright",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("binary_path", help="Path to the Camoufox (Firefox) binary")
    parser.add_argument(
        "--profile-count", type=int, default=8, metavar="N",
        help="Number of profiles to test, 1-8 (default: 8)",
    )
    parser.add_argument(
        "--secret", default="camoufox-tester-dev-secret", metavar="KEY",
        help="HMAC signing key for the certificate (default: dev secret)",
    )
    parser.add_argument(
        "--save-cert", metavar="PATH",
        help="Save the ASCII certificate to this file",
    )
    parser.add_argument(
        "--no-cert", action="store_true",
        help="Skip certificate generation",
    )
    args = parser.parse_args()

    profile_count = max(1, min(8, args.profile_count))

    binary_path = args.binary_path
    # Resolve macOS .app bundle to internal binary
    if sys.platform == "darwin" and binary_path.endswith(".app"):
        candidate = os.path.join(binary_path, "Contents", "MacOS", "camoufox")
        if os.path.isfile(candidate):
            binary_path = candidate
        else:
            candidate2 = os.path.join(binary_path, "Contents", "MacOS", "firefox")
            if os.path.isfile(candidate2):
                binary_path = candidate2

    if not os.path.isfile(binary_path):
        print(f"ERROR: Binary not found: {binary_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Camoufox Build Tester")
    print(f"Binary:   {binary_path}")
    print(f"Profiles: {profile_count}")

    exit_code = asyncio.run(
        run_tests(
            binary_path=binary_path,
            profile_count=profile_count,
            secret=args.secret,
            save_cert=args.save_cert,
            no_cert=args.no_cert,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
