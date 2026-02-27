"""
LUCID EMPIRE :: COMMERCE INJECTOR
Purpose: Injects localStorage artifacts AND dispatches StorageEvents.
"""
async def inject_trust_anchors(page, platform="shopify"):
    print(f"   [*] Injecting Commerce Vector: {platform.upper()}")


    # The Double-Tap Script
    script = """
    (args) => {
        const [key, value] = args;
        window.localStorage.setItem(key, value);
        const event = new StorageEvent('storage', {
            key: key, newValue: value,
            url: window.location.href, storageArea: window.localStorage,
            bubbles: true, cancelable: false
        });
        window.dispatchEvent(event);
    }
    """


    if platform == "shopify":
        token = "c1234567-89ab-cdef-0123-4567890abcdef"
        await page.evaluate(script, ["checkout_token", token])
        await page.evaluate(script, ["shopify_pay_redirect_cookie", "true"])
    
    # Add other platforms (Stripe, Amazon) as needed
