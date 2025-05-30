"""
Advanced anti-detection features for Camoufox
"""

import re
import secrets
from typing import Any, Dict, List, Optional, Tuple
from random import choice, uniform

from .utils import merge_into, set_into


def generate_client_hints(user_agent: str, mobile: bool = False) -> Dict[str, Any]:
    """
    Generate Client Hints based on User-Agent string.
    """
    # Parse major version from UA
    version_match = re.search(r'Chrome/(\d+)', user_agent)
    if not version_match:
        # Firefox UA, generate Firefox-compatible brands
        firefox_match = re.search(r'Firefox/(\d+)', user_agent)
        if firefox_match:
            major_version = firefox_match.group(1)
            brands = [
                {"brand": "Firefox", "version": major_version},
                {"brand": "Not_A Brand", "version": "99"},
            ]
        else:
            return {}
    else:
        major_version = version_match.group(1)
        # Generate realistic brand combinations
        brands = [
            {"brand": "Chromium", "version": major_version},
            {"brand": "Google Chrome", "version": major_version},
            {"brand": "Not_A Brand", "version": "99"},
        ]
    
    # Extract platform from UA
    platform = "Windows"
    if "Macintosh" in user_agent:
        platform = "macOS"
    elif "Linux" in user_agent:
        platform = "Linux"
    elif "Android" in user_agent:
        platform = "Android"
    
    return {
        "navigator.userAgentData.brands": brands,
        "navigator.userAgentData.mobile": mobile,
        "navigator.userAgentData.platform": platform,
    }


def generate_device_memory() -> int:
    """
    Generate realistic device memory value.
    """
    # Common memory values in GB
    memory_values = [2, 4, 8]
    # Weight towards higher values for modern devices
    weights = [0.2, 0.5, 0.3]
    return choice([memory_values[i] for i in range(len(memory_values)) for _ in range(int(weights[i] * 10))])


def generate_network_info(connection_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate realistic Network Information API values.
    """
    if not connection_type:
        connection_type = choice(['4g', '4g', '4g', '3g', 'wifi'])  # Weight towards 4g
    
    network_profiles = {
        '4g': {
            'effectiveType': '4g',
            'rtt': secrets.randbelow(50) + 50,  # 50-100ms
            'downlink': uniform(5.0, 10.0),
            'saveData': False,
        },
        '3g': {
            'effectiveType': '3g',
            'rtt': secrets.randbelow(200) + 100,  # 100-300ms
            'downlink': uniform(1.0, 3.0),
            'saveData': choice([True, False]),
        },
        '2g': {
            'effectiveType': '2g',
            'rtt': secrets.randbelow(500) + 300,  # 300-800ms
            'downlink': uniform(0.1, 0.5),
            'saveData': True,
        },
        'wifi': {
            'effectiveType': '4g',
            'rtt': secrets.randbelow(30) + 20,  # 20-50ms
            'downlink': uniform(10.0, 50.0),
            'saveData': False,
        },
    }
    
    profile = network_profiles.get(connection_type, network_profiles['4g'])
    return {
        f"navigator.connection.{key}": value 
        for key, value in profile.items()
    }


def generate_storage_quota(usage_percentage: float = 0.1) -> Dict[str, Any]:
    """
    Generate realistic storage quota values.
    """
    # Total storage in bytes (1GB to 10GB)
    total = choice([
        1 * 1024**3,    # 1GB
        2 * 1024**3,    # 2GB
        5 * 1024**3,    # 5GB
        10 * 1024**3,   # 10GB
    ])
    
    # Usage based on percentage
    usage = int(total * usage_percentage * uniform(0.8, 1.2))
    
    return {
        "storage:quota:total": total,
        "storage:quota:usage": min(usage, total),
    }


def generate_permissions_state(profile: str = 'default') -> Dict[str, Any]:
    """
    Generate consistent permission states based on profile.
    """
    profiles = {
        'default': {
            'geolocation': 'prompt',
            'notifications': 'prompt',
            'camera': 'prompt',
            'microphone': 'prompt',
            'clipboard-read': 'denied',
            'clipboard-write': 'granted',
        },
        'permissive': {
            'geolocation': 'granted',
            'notifications': 'granted',
            'camera': 'granted',
            'microphone': 'granted',
            'clipboard-read': 'granted',
            'clipboard-write': 'granted',
        },
        'restrictive': {
            'geolocation': 'denied',
            'notifications': 'denied',
            'camera': 'denied',
            'microphone': 'denied',
            'clipboard-read': 'denied',
            'clipboard-write': 'denied',
        },
        'mixed': {
            'geolocation': choice(['granted', 'denied', 'prompt']),
            'notifications': choice(['granted', 'denied']),
            'camera': 'prompt',
            'microphone': 'prompt',
            'clipboard-read': 'denied',
            'clipboard-write': 'granted',
        },
    }
    
    return {
        "permissions:state": profiles.get(profile, profiles['default'])
    }


def enable_performance_fuzzing(max_jitter: float = 1.0) -> Dict[str, Any]:
    """
    Enable Performance API timing fuzzing to prevent timing attacks.
    """
    return {
        "performance:timingFuzz": True,
        "performance:timingFuzz:maxJitter": max_jitter,
    }


def enable_canvas_protection(noise_level: float = 0.001, text_noise: bool = True) -> Dict[str, Any]:
    """
    Enable canvas fingerprinting protection with noise injection.
    """
    return {
        "canvas:noise": True,
        "canvas:noiseLevel": noise_level,
        "canvas:textNoise": text_noise,
        "canvas:textNoiseLevel": uniform(0.05, 0.2) if text_noise else 0,
    }


def enable_scroll_humanization(speed_multiplier: float = 1.0) -> Dict[str, Any]:
    """
    Enable human-like scroll behavior.
    """
    return {
        "scroll:humanize": True,
        "scroll:humanize:speed": speed_multiplier * uniform(0.8, 1.2),
        "scroll:humanize:acceleration": uniform(0.9, 1.1),
    }


def apply_advanced_antidetect(config: Dict[str, Any], **options) -> None:
    """
    Apply advanced anti-detection features to config.
    
    Options:
        enable_client_hints: bool - Enable Client Hints API spoofing
        enable_device_apis: bool - Enable device memory and network info
        enable_canvas_protection: bool - Enable canvas fingerprinting protection
        enable_timing_fuzzing: bool - Enable performance timing fuzzing
        enable_scroll_humanization: bool - Enable human-like scrolling
        enable_permissions: bool - Enable permissions spoofing
        enable_storage_quota: bool - Enable storage quota spoofing
    """
    # Client Hints
    if options.get('enable_client_hints', True):
        user_agent = config.get('navigator.userAgent', '')
        if user_agent:
            merge_into(config, generate_client_hints(user_agent))
    
    # Device APIs
    if options.get('enable_device_apis', True):
        set_into(config, 'navigator.deviceMemory', generate_device_memory())
        merge_into(config, generate_network_info())
    
    # Canvas Protection
    if options.get('enable_canvas_protection', True):
        merge_into(config, enable_canvas_protection())
    
    # Timing Fuzzing
    if options.get('enable_timing_fuzzing', True):
        merge_into(config, enable_performance_fuzzing())
    
    # Scroll Humanization
    if options.get('enable_scroll_humanization', False):  # Off by default for performance
        merge_into(config, enable_scroll_humanization())
    
    # Permissions
    if options.get('enable_permissions', True):
        merge_into(config, generate_permissions_state())
    
    # Storage Quota
    if options.get('enable_storage_quota', True):
        merge_into(config, generate_storage_quota())


# Re-export for convenience
__all__ = [
    'apply_advanced_antidetect',
    'generate_client_hints',
    'generate_device_memory',
    'generate_network_info',
    'generate_storage_quota',
    'generate_permissions_state',
    'enable_performance_fuzzing',
    'enable_canvas_protection',
    'enable_scroll_humanization',
]