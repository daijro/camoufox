"""
LUCID EMPIRE :: GENESIS ENGINE


Environment: Linux (GitHub Codespaces / Docker)
Purpose: Generates a browser profile and ages it 90 days in the past. Dependencies: lucid, playwright, libfaketime (system package)
"""
import os
import json
import asyncio
import random
from playwright.async_api import async_playwright
import datetime

# Import Lucid Empire Modules
from humanization import Humanizer
from commerce_injector import inject_trust_anchors

# --- CONFIGURATION ---
PROFILE_DIR = "./lucid_profile_data"
GOLDEN_TEMPLATE_PATH = "./golden_template.json"

# Load the Golden Template (The "Soul")
if not os.path.exists(GOLDEN_TEMPLATE_PATH):
    # In a real scenario, we might raise an error, but for now we'll warn or just use placeholders if needed.
    # raise FileNotFoundError("CRITICAL: 'golden_template.json' not found. Run Harvester first.")
    print("WARNING: 'golden_template.json' not found. Ensure it exists before full run.")
    GOLDEN_TEMPLATE = None
else:
    with open(GOLDEN_TEMPLATE_PATH, 'r') as f:
        GOLDEN_TEMPLATE = json.load(f)

async def run_temporal_displacement(faketime_offset):
    """
    Launches Lucid with specific libfaketime environment variables.
    """
    print(f"[*] INITIATING TEMPORAL DISPLACEMENT: {faketime_offset}")

    # Environment variables for Time Travel
    env = os.environ.copy()
    env["LD_PRELOAD"] = "/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1" # Path varies by distro
    env["FAKETIME"] = faketime_offset
    env["DONT_FAKE_MONOTONIC"] = "1" # CRITICAL: Prevents Firefox deadlocks
    env["FAKETIME_NO_CACHE"] = "1"

    async with async_playwright() as p:
        # Note: We are using standard Firefox launch here but pointing to our Lucid binary if compiled,
        # or standard Lucid for the data generation phase if binary isn't ready.
        # Ideally, this runs against the Linux build of Lucid.
        
        user_agent = GOLDEN_TEMPLATE['navigator']['userAgent'] if GOLDEN_TEMPLATE else "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/109.0"
        viewport = {"width": GOLDEN_TEMPLATE['screen']['width'], "height": GOLDEN_TEMPLATE['screen']['height']} if GOLDEN_TEMPLATE else {"width": 1920, "height": 1080}

        browser = await p.firefox.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            env=env, # Inject Time Travel
            user_agent=user_agent,
            viewport=viewport
        )

        page = browser.pages[0]
        human = Humanizer(page)

        # --- PHASE 1: THE WARMING (History Generation) ---
        print(" > Visiting Trust Anchors...")
        trust_anchors = ["https://www.wikipedia.org", "https://weather.com", "https://www.cnn.com"]
        for url in trust_anchors:
            try:
                await page.goto(url, wait_until="domcontentloaded")
                # Human-like cursor movement over the page to generate behavior data
                await human.move_mouse(random.randint(100, 800), random.randint(100, 600))
                await page.wait_for_timeout(random.randint(1000, 3000))
                print(f"    + Indexed: {url}")
            except Exception as e:
                print(f"    ! Failed to visit {url}: {e}")


        # --- PHASE 2: COMMERCE INJECTION (Double-Tap Protocol) ---
        print(" > Injecting Commerce Artifacts...")
        try:
            await page.goto("https://www.google.com") # Need a valid origin for localStorage
            
            # Use the Commerce Injector Module
            await inject_trust_anchors(page, platform="generic")
            await inject_trust_anchors(page, platform="shopify")
            
            print(" > Artifacts Injected.")
        except Exception as e:
            print(f" > Injection Warning: {e}")

        # --- PHASE 3: THE BRIDGE (Export) ---
        print(" > Exporting Bridge File...")
        cookies = await browser.cookies()

        bridge_file = os.path.join(PROFILE_DIR, "profile_bridge.json")
        with open(bridge_file, "w") as f:
            json.dump(cookies, f, indent=2)

        print(f" > SUCCESS. Bridge file created at: {bridge_file}")
        await browser.close()

async def main():
    if not GOLDEN_TEMPLATE:
        print("CRITICAL: Skipping temporal displacement due to missing Golden Template.")
        return

    # 1. T-90 Days: Inception
    await run_temporal_displacement("-90d")

    # 2. T-30 Days: Activity
    await run_temporal_displacement("-30d")

    # 3. T-0 Days: Final Sync
    await run_temporal_displacement("-0d")

    print("\n[V] GENESIS COMPLETE. Copy 'lucid_profile_data' to your Windows machine.")

if __name__ == "__main__":
    asyncio.run(main())
