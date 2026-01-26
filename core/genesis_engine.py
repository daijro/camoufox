"""
LUCID EMPIRE :: GENESIS ENGINE v2.0
Purpose: Orchestrates Temporal Displacement and the 15-Minute Warm-Up Cycle.
"""
import os
import json
import asyncio
import random
from playwright.async_api import async_playwright
from modules.commerce_injector import inject_trust_anchors
from modules.humanization import human_scroll, human_mouse_move


PROFILE_DIR = "./lucid_profile_data"


async def run_warmup_phase(page, phase_name):
    print(f" [>] STARTING PHASE: {phase_name}")
    
    if phase_name == "RAM_PRIMING":
        # Minutes 0-5: News Sites (Read-Only)
        urls = ["https://www.cnn.com", "https://www.bbc.com", "https://www.reuters.com"]
        for url in urls:
            try:
                await page.goto(url, wait_until="domcontentloaded")
                await human_scroll(page)
                await asyncio.sleep(random.randint(5, 10))
            except: pass


    elif phase_name == "TRUST_ANCHORS":
        # Minutes 5-10: Login & Address Fill
        # Simulating interaction with a high-trust site
        try:
            await page.goto("https://www.apple.com/shop/bag", wait_until="networkidle")
            await human_mouse_move(page)
            # Inject Commerce Artifacts here to simulate 'remembered' state
            await inject_trust_anchors(page, platform="shopify")
        except: pass


    elif phase_name == "KILL_CHAIN":
        # Minutes 10-15: Cart & Hesitation
        try:
            await page.goto("https://www.amazon.com")
            await human_mouse_move(page)
            await asyncio.sleep(random.randint(3, 5)) # Micro-hesitation
            # Simulate "Add to Cart" logic would go here
        except: pass


async def main():
    async with async_playwright() as p:
        # Launch with Time Travel Env Vars (from previous steps)
        browser = await p.firefox.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            viewport={"width": 1920, "height": 1080}
        )
        page = browser.pages[0]


        # EXECUTE 15-MINUTE CYCLE
        await run_warmup_phase(page, "RAM_PRIMING")
        await run_warmup_phase(page, "TRUST_ANCHORS")
        await run_warmup_phase(page, "KILL_CHAIN")


        print(" [V] GENESIS COMPLETE. Profile Aged & Warmed.")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
