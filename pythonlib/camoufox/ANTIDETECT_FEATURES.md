# Advanced Anti-Detection Features

This document describes the new advanced anti-detection features added to Camoufox.

## Features Overview

### 1. Performance API Timing Fuzzing
Prevents timing-based fingerprinting attacks by adding random jitter to high-resolution timers.

```python
config = {
    "performance:timingFuzz": True,
    "performance:timingFuzz:maxJitter": 1.0  # Max jitter in milliseconds
}
```

### 2. Canvas Fingerprinting Protection
Adds imperceptible noise to canvas operations to prevent canvas fingerprinting.

```python
config = {
    "canvas:noise": True,
    "canvas:noiseLevel": 0.001,  # Noise level for image data
    "canvas:textNoise": True,
    "canvas:textNoiseLevel": 0.1  # Noise level for text rendering
}
```

### 3. Client Hints API Spoofing
Implements the modern Client Hints API for better Chrome compatibility.

```python
config = {
    "navigator.userAgentData.brands": [
        {"brand": "Chromium", "version": "119"},
        {"brand": "Google Chrome", "version": "119"},
        {"brand": "Not_A Brand", "version": "99"}
    ],
    "navigator.userAgentData.mobile": False,
    "navigator.userAgentData.platform": "Windows"
}
```

### 4. Device Memory API
Spoofs the Device Memory API to match typical hardware configurations.

```python
config = {
    "navigator.deviceMemory": 8  # Memory in GB (2, 4, or 8)
}
```

### 5. Network Information API
Provides realistic network connection information.

```python
config = {
    "navigator.connection.effectiveType": "4g",
    "navigator.connection.rtt": 75,  # Round-trip time in ms
    "navigator.connection.downlink": 8.5,  # Mbps
    "navigator.connection.saveData": False
}
```

### 6. Permissions API State
Controls the state of various browser permissions.

```python
config = {
    "permissions:state": {
        "geolocation": "prompt",
        "notifications": "denied",
        "camera": "prompt",
        "microphone": "prompt",
        "clipboard-read": "denied",
        "clipboard-write": "granted"
    }
}
```

### 7. Storage Quota API
Spoofs storage quota to appear like a real browser with usage.

```python
config = {
    "storage:quota:total": 5368709120,  # 5GB in bytes
    "storage:quota:usage": 536870912    # 500MB in bytes
}
```

### 8. Scroll Behavior Humanization
Makes scrolling behavior more human-like with variable speeds and acceleration.

```python
config = {
    "scroll:humanize": True,
    "scroll:humanize:speed": 1.0,  # Speed multiplier
    "scroll:humanize:acceleration": 1.0  # Acceleration factor
}
```

## Usage with Python API

All these features are automatically applied when using Camoufox:

```python
from camoufox.sync_api import Camoufox

with Camoufox() as browser:
    # All anti-detection features are enabled by default
    page = browser.new_page()
    page.goto('https://example.com')
```

To customize specific features:

```python
from camoufox.sync_api import Camoufox

config = {
    # Disable canvas protection for specific use case
    "canvas:noise": False,
    
    # Custom network profile
    "navigator.connection.effectiveType": "3g",
    "navigator.connection.rtt": 150,
    
    # Custom permissions
    "permissions:state": {
        "geolocation": "granted",
        "notifications": "granted"
    }
}

with Camoufox(config=config) as browser:
    page = browser.new_page()
```

## Implementation Notes

### Security Considerations
- All random values use `secrets` module for cryptographic security
- Timing jitter is applied consistently to avoid statistical detection
- Canvas noise is applied at sub-pixel level to be imperceptible

### Performance Impact
- Performance timing fuzzing: Minimal (~0.1% overhead)
- Canvas protection: Low (~1-2% overhead on canvas operations)
- Scroll humanization: Medium (disabled by default)
- Other features: Negligible impact

### Compatibility
- All features gracefully degrade if not supported
- Client Hints only active when spoofing Chrome user agents
- Network Information API returns realistic values based on geolocation

## Future Enhancements

Planned additions:
1. WebRTC STUN/TURN fingerprinting protection
2. AudioContext waveform noise injection
3. WebGL shader precision fuzzing
4. Font rendering microsecond timing variations
5. TCP/TLS fingerprint randomization