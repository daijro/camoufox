"""
PROMETHEUS-CORE GENESIS ENGINE (PHASE 5)
Orchestrates the 15-minute Warm-Up Cycle and enforces 'Persona Logic'.
"""
import asyncio
import random
import json
import os
import sys
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


class GenesisEngine:
    """
    PHASE 5 IMPLEMENTATION
    Adds persona-based hardware masking and forensic aging
    """
    def __init__(self, profile_path, proxy=None, headless=False, identity_data=None):
        self.profile_path = profile_path
        self.proxy = proxy
        self.headless = headless
        self.identity = identity_data or {}
        self.browser = None
        self.context = None
        self.page = None
        
        # PHASE 5: PERSONA SELECTION
        self.persona_config = self._derive_persona_from_identity()


    async def run_warmup_phase(self, phase_name):
        if not self.page: await self.launch()
        
        print(f"[{phase_name}] EXECUTING...")
        
        if phase_name == "RAM_PRIMING":
            # Visit High-Entropy sites to load cookies
            sites = ["https://cnn.com", "https://wikipedia.org", "https://bbc.com"]
            for site in sites:
                try:
                    await self.page.goto(site, timeout=30000)
                    await self._human_scroll()
                except: pass

        elif phase_name == "TRUST_ANCHORS":
            # Simulate "Checking Identity"
            await self.page.goto("https://whoer.net")
            await asyncio.sleep(5)
            await self._human_scroll()

        elif phase_name == "KILL_CHAIN":
            # Wait for user or simulate checkout
            print("[KILL CHAIN] Handing over to Operator or waiting...")
            await asyncio.sleep(60)


    async def launch(self):
        """Launch browser with persona-based configuration"""
        playwright = await async_playwright().start()
        
        # Load Aging Config
        aging_config = {}
        try:
            with open(os.path.join(self.profile_path, "aging_config.json"), "r") as f:
                aging_config = json.load(f)
        except:
            pass
            
        # Initialize with persona settings
        self.context = await playwright.firefox.launch_persistent_context(
            user_data_dir=self.profile_path,
            headless=self.headless,
            user_agent=self.persona_config['user_agent'],
            viewport=self.persona_config['viewport'],
            device_scale_factor=self.persona_config['device_scale_factor'],
            proxy={"server": self.proxy} if self.proxy else None,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        self.page = self.context.pages[0]
        
        # Inject Platform Spoofing
        await self.page.add_init_script(f"""
            Object.defineProperty(navigator, 'platform', {{
                get: () => '{self.persona_config['platform']}'
            }});
        """)


    async def main(self, zip_code: str):
        """Main entry point with ZIP-based persona selection"""
        profile = ProfileSelector.get_profile(zip_code)
        template = f"./templates/{profile}.json"
        
        await self.launch()

        # EXECUTE 15-MINUTE CYCLE
        await self.run_warmup_phase("RAM_PRIMING")
        await self.run_warmup_phase("TRUST_ANCHORS")
        await self.run_warmup_phase("KILL_CHAIN")

        print(" [V] GENESIS COMPLETE. Profile Aged & Warmed.")
        await self.browser.close()


    def _derive_persona_from_identity(self):
        """
        [PHASE 5 INTELLIGENCE]
        Analyzes the 'Fullz' (Zip Code / BIN) to select the appropriate hardware mask.
        """
        zip_code = self.identity.get('zip', '00000')
        # Simple heuristic: Wealthy zips get High-End Mac/PC
        wealthy_zips = ['90210', '10001', '33109', '94027'] 
        
        if any(z in zip_code for z in wealthy_zips):
            print("[GENESIS] HIGH-VALUE TARGET DETECTED. Deploying 'Silicon Valley' Persona.")
            return {
                "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
                "viewport": {"width": 1728, "height": 1117}, # MacBook Pro 16"
                "device_scale_factor": 2,
                "platform": "MacIntel"
            }
        else:
            print("[GENESIS] STANDARD TARGET. Deploying 'Windows 10' Persona.")
            return {
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "viewport": {"width": 1920, "height": 1080},
                "device_scale_factor": 1,
                "platform": "Win32"
            }


    async def _human_scroll(self):
        await human_scroll(self.page)


if __name__ == "__main__":
    # Simple CLI for testing
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="manual")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--aging", type=int, default=7)
    args = parser.parse_args()
    
    engine = GenesisEngine(f"profiles/{args.profile}")
    asyncio.run(engine.launch())
