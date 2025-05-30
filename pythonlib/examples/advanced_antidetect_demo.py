#!/usr/bin/env python3
"""
Demonstration of Camoufox's advanced anti-detection features
"""

from camoufox.sync_api import Camoufox
import json


def test_antidetect_features():
    """
    Test page that checks for various browser APIs and fingerprinting vectors
    """
    test_script = """
    async function checkFeatures() {
        const results = {};
        
        // Check Performance API timing
        const t1 = performance.now();
        await new Promise(r => setTimeout(r, 10));
        const t2 = performance.now();
        results.performanceTiming = {
            hasJitter: (t2 - t1) % 1 !== 0,
            delta: t2 - t1
        };
        
        // Check Client Hints API
        results.clientHints = {
            hasUserAgentData: 'userAgentData' in navigator,
            brands: navigator.userAgentData?.brands || null,
            mobile: navigator.userAgentData?.mobile || null,
            platform: navigator.userAgentData?.platform || null
        };
        
        // Check Device APIs
        results.deviceAPIs = {
            deviceMemory: navigator.deviceMemory || 'not supported',
            connection: navigator.connection ? {
                effectiveType: navigator.connection.effectiveType,
                rtt: navigator.connection.rtt,
                downlink: navigator.connection.downlink,
                saveData: navigator.connection.saveData
            } : 'not supported'
        };
        
        // Check Canvas fingerprinting
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        ctx.fillText('Canvas fingerprint test', 10, 10);
        const dataUrl = canvas.toDataURL();
        results.canvas = {
            dataUrlLength: dataUrl.length,
            sample: dataUrl.substring(0, 50)
        };
        
        // Check Permissions API
        const permissions = ['geolocation', 'notifications', 'camera', 'microphone'];
        results.permissions = {};
        for (const perm of permissions) {
            try {
                const result = await navigator.permissions.query({name: perm});
                results.permissions[perm] = result.state;
            } catch (e) {
                results.permissions[perm] = 'error: ' + e.message;
            }
        }
        
        // Check Storage Quota
        if (navigator.storage && navigator.storage.estimate) {
            const estimate = await navigator.storage.estimate();
            results.storageQuota = {
                quota: estimate.quota,
                usage: estimate.usage,
                percentage: (estimate.usage / estimate.quota * 100).toFixed(2) + '%'
            };
        }
        
        return results;
    }
    
    checkFeatures();
    """
    
    # Run with default anti-detection features
    print("Testing with default anti-detection features enabled...")
    with Camoufox() as browser:
        page = browser.new_page()
        page.goto('about:blank')
        
        results = page.evaluate(test_script)
        print(json.dumps(results, indent=2))
        
    print("\n" + "="*50 + "\n")
    
    # Run with custom configuration
    print("Testing with custom anti-detection configuration...")
    custom_config = {
        # Custom Client Hints
        "navigator.userAgentData.brands": [
            {"brand": "My Custom Browser", "version": "1.0"},
            {"brand": "Chromium", "version": "119"},
        ],
        "navigator.userAgentData.mobile": False,
        "navigator.userAgentData.platform": "Windows",
        
        # Custom device memory (high-end device)
        "navigator.deviceMemory": 8,
        
        # Custom network (fast connection)
        "navigator.connection.effectiveType": "4g",
        "navigator.connection.rtt": 50,
        "navigator.connection.downlink": 10.0,
        "navigator.connection.saveData": False,
        
        # Custom permissions (privacy-focused)
        "permissions:state": {
            "geolocation": "denied",
            "notifications": "denied",
            "camera": "denied",
            "microphone": "denied"
        },
        
        # Enable all protection features
        "performance:timingFuzz": True,
        "performance:timingFuzz:maxJitter": 2.0,
        "canvas:noise": True,
        "canvas:noiseLevel": 0.002,
        "canvas:textNoise": True,
        "canvas:textNoiseLevel": 0.1,
    }
    
    with Camoufox(config=custom_config) as browser:
        page = browser.new_page()
        page.goto('about:blank')
        
        results = page.evaluate(test_script)
        print(json.dumps(results, indent=2))


def test_fingerprinting_sites():
    """
    Test against popular fingerprinting test sites
    """
    print("\nTesting against fingerprinting sites...")
    
    test_sites = [
        ("CreepJS", "https://abrahamjuliot.github.io/creepjs/"),
        ("BrowserLeaks Canvas", "https://browserleaks.com/canvas"),
        ("AmIUnique", "https://amiunique.org/fingerprint"),
    ]
    
    with Camoufox() as browser:
        for name, url in test_sites:
            print(f"\nTesting {name}...")
            page = browser.new_page()
            
            try:
                page.goto(url, wait_until='networkidle', timeout=30000)
                page.wait_for_timeout(3000)  # Let the page fully load
                
                # Take a screenshot for manual inspection
                screenshot_path = f"antidetect_test_{name.lower().replace(' ', '_')}.png"
                page.screenshot(path=screenshot_path)
                print(f"Screenshot saved: {screenshot_path}")
                
            except Exception as e:
                print(f"Error testing {name}: {e}")
            finally:
                page.close()


if __name__ == "__main__":
    print("Camoufox Advanced Anti-Detection Features Demo")
    print("=" * 50)
    
    # Test anti-detection features
    test_antidetect_features()
    
    # Uncomment to test against fingerprinting sites
    # test_fingerprinting_sites()
    
    print("\nDemo completed!")