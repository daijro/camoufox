import argparse
import subprocess
import time

from camoufox.pkgman import launch_path
from camoufox.sync_api import Camoufox
from camoufox.virtdisplay import VirtualDisplay
from playwright.sync_api import sync_playwright
from tabulate import tabulate

# URLs to benchmark
urls = ["about:blank", "https://google.com", "https://yahoo.com"]


def get_firefox_memory(name):
    """Get the total memory usage of all processes named 'firefox'."""
    try:
        result = subprocess.run(["ps", "-C", name, "-o", "rss="], capture_output=True, text=True)
        memory_kb = sum(int(line.strip()) for line in result.stdout.splitlines())
        memory_mb = memory_kb / 1024  # Convert KB to MB
        return memory_mb
    except Exception as e:
        print(f"Error getting Firefox memory: {e}")
        return 0


def get_average_memory(name, duration):
    """Monitor memory usage for Firefox over a duration (seconds) and return the average."""
    memory_samples = []
    for n in range(duration):
        memory_samples.append(get_firefox_memory(name))
        # print(f"> Mem ({n}sec): {memory_samples[-1]} MB")
        time.sleep(1)
    return sum(memory_samples) / len(memory_samples) if memory_samples else 0


def run_playwright(mode, browser_name):
    headless = mode == "headless"
    memory_usage = []
    # Set up virtual display
    virt = VirtualDisplay()
    env = {"DISPLAY": virt.get()}

    if browser_name == "camoufox-ubo":
        camoufox = Camoufox(headless=headless, env=env)
        browser = camoufox.start()
    elif browser_name == "firefox":
        playwright = sync_playwright().start()
        browser = playwright.firefox.launch(headless=headless, env=env)
    elif browser_name == "camoufox":
        playwright = sync_playwright().start()
        browser = playwright.firefox.launch(
            headless=headless, env=env, executable_path=launch_path()
        )

    for url in urls:
        page = browser.new_page()
        page.goto(url)
        time.sleep(5)  # Allow the page to load
        memory = get_average_memory(
            name="camoufox-bin" if browser_name.startswith('camoufox') else 'firefox', duration=10
        )
        memory_usage.append((url, memory))
        page.close()

    browser.close()

    return memory_usage


if __name__ == "__main__":
    # Set up argument parsing
    parser = argparse.ArgumentParser(description="Run a browser memory benchmark.")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["headless", "headful"],
        required=True,
        help="Mode to run the browser in (headless or headful).",
    )
    parser.add_argument(
        "--browser",
        type=str,
        choices=["firefox", "camoufox", "camoufox-ubo"],
        required=True,
        help="Browser to use for the benchmark.",
    )

    args = parser.parse_args()

    # Run the benchmark
    results = run_playwright(args.mode, args.browser)

    # Format results as a table
    print(f"\n=== MEMORY RESULTS FOR {args.browser.upper()} ===")
    table = [["URL", "Memory Usage (MB)"]] + results
    print(tabulate(table, headers="firstrow", tablefmt="grid"))
