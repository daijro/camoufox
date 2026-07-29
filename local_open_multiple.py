import argparse
import tempfile
from contextlib import ExitStack
from pathlib import Path

from camoufox.sync_api import Camoufox


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open multiple Camoufox browser windows.")
    parser.add_argument("-n", "--count", type=int, default=3, help="Number of browser windows to open.")
    parser.add_argument("--url", default="https://example.com", help="URL to open in each window.")
    parser.add_argument(
        "--profile-root",
        default=str(Path(tempfile.gettempdir()) / "camoufox-multi-profiles"),
        help="Directory used to store separate browser profiles.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    profile_root = Path(args.profile_root)
    profile_root.mkdir(parents=True, exist_ok=True)

    with ExitStack() as stack:
        contexts = []
        for index in range(args.count):
            profile_dir = profile_root / f"profile-{index + 1}"
            profile_dir.mkdir(parents=True, exist_ok=True)

            context = stack.enter_context(
                Camoufox(
                    headless=False,
                    persistent_context=True,
                    user_data_dir=str(profile_dir),
                )
            )
            page = context.new_page()
            page.goto(args.url)
            contexts.append(context)
            print(f"Opened Camoufox #{index + 1}: {args.url}")

        input("Press Enter to close all browsers...")


if __name__ == "__main__":
    main()
