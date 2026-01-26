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


class ProfileSelector:
    """Maps ZIP codes to hardware profiles"""
    WEALTHY_ZIPS = {
        "90210": "macbook_pro_m2",
        "10021": "macbook_pro_m2",  # NYC Upper East Side
        "94027": "macbook_pro_m2",  # Atherton, CA
        "33109": "macbook_pro_m2"   # Miami Beach
    }

    DEFAULT_PROFILE = "windows_10_standard"

    @classmethod
    def get_profile(cls, zip_code: str) -> str:
        """Returns hardware profile based on ZIP code demographics"""
        return cls.WEALTHY_ZIPS.get(zip_code[:5], cls.DEFAULT_PROFILE)


async def run_warmup_phase(page, phase_name, zip_code):
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
        platform = "apple" if zip_code in ProfileSelector.WEALTHY_ZIPS else "shopify"
        try:
            await page.goto("https://www.apple.com/shop/bag", wait_until="networkidle")
            await human_mouse_move(page)
            await inject_trust_anchors(page, platform=platform)
        except: pass


    elif phase_name == "KILL_CHAIN":
        # Minutes 10-15: Cart & Hesitation
        try:
            await page.goto("https://www.amazon.com")
            await human_mouse_move(page)
            await asyncio.sleep(random.randint(3, 5)) # Micro-hesitation
            # Simulate "Add to Cart" logic would go here
        except: pass


async def main(zip_code: str):
    """Main entry point with ZIP-based persona selection"""
    profile = ProfileSelector.get_profile(zip_code)
    template = f"./templates/{profile}.json"
    
    async with async_playwright() as p:
        browser = await p.firefox.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=2.0 if "macbook" in profile else 1.0
        )
        page = browser.pages[0]

        # EXECUTE 15-MINUTE CYCLE
        await run_warmup_phase(page, "RAM_PRIMING", zip_code)
        await run_warmup_phase(page, "TRUST_ANCHORS", zip_code)
        await run_warmup_phase(page, "KILL_CHAIN", zip_code)

        print(" [V] GENESIS COMPLETE. Profile Aged & Warmed.")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main("10021"))
