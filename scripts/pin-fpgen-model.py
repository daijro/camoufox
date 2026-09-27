#!/usr/bin/env python3
"""Install the pinned fpgen model before anything imports fpgen.

The launcher does this itself on first use (pythonlib/camoufox/fpgen_model.py,
which explains why fpgen's own download is not used). This entry point exists
for jobs that need the model in place before they start: CI, image builds, and
the TypeScript golden recorder.

Usage:
    python3 scripts/pin-fpgen-model.py           # install if not already pinned
    python3 scripts/pin-fpgen-model.py --check    # verify only; non-zero if not pinned
    python3 scripts/pin-fpgen-model.py --force    # re-download and reinstall
"""

import argparse
import sys

try:
    from camoufox.fpgen_model import PIN, ensure_fpgen_model, fpgen_data_dir, is_pinned
except ImportError:
    sys.exit('camoufox is not installed; `pip install -e pythonlib` first')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true', help='verify only; non-zero if not pinned')
    ap.add_argument('--force', action='store_true', help='reinstall even if already pinned')
    args = ap.parse_args()

    if args.check:
        if is_pinned():
            print(f'OK: fpgen model pinned to {PIN["tag"]}')
            return 0
        print(f'fpgen model is NOT pinned to {PIN["tag"]}; run scripts/pin-fpgen-model.py',
              file=sys.stderr)
        return 1

    ensure_fpgen_model(force=args.force)
    print(f'OK: fpgen model {PIN["tag"]} pinned in {fpgen_data_dir()}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
