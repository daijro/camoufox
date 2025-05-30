"""
Tests for advanced anti-detection features
"""

import pytest
from camoufox.antidetect import (
    generate_client_hints,
    generate_device_memory,
    generate_network_info,
    generate_storage_quota,
    generate_permissions_state,
    enable_performance_fuzzing,
    enable_canvas_protection,
    enable_scroll_humanization,
    apply_advanced_antidetect
)


def test_generate_client_hints():
    """Test Client Hints generation for different user agents"""
    # Chrome UA
    chrome_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    hints = generate_client_hints(chrome_ua)
    assert "navigator.userAgentData.brands" in hints
    assert len(hints["navigator.userAgentData.brands"]) >= 2
    assert hints["navigator.userAgentData.platform"] == "Windows"
    assert hints["navigator.userAgentData.mobile"] is False
    
    # Firefox UA
    firefox_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15) Gecko/20100101 Firefox/118.0"
    hints = generate_client_hints(firefox_ua)
    assert hints["navigator.userAgentData.platform"] == "macOS"
    
    # Mobile UA
    mobile_ua = "Mozilla/5.0 (Linux; Android 10; SM-G960U) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.5060.94 Mobile Safari/537.36"
    hints = generate_client_hints(mobile_ua, mobile=True)
    assert hints["navigator.userAgentData.mobile"] is True
    assert hints["navigator.userAgentData.platform"] == "Android"


def test_generate_device_memory():
    """Test device memory generation"""
    for _ in range(10):
        memory = generate_device_memory()
        assert memory in [2, 4, 8]


def test_generate_network_info():
    """Test network info generation"""
    # Test 4G profile
    info = generate_network_info('4g')
    assert info["navigator.connection.effectiveType"] == '4g'
    assert 50 <= info["navigator.connection.rtt"] <= 100
    assert 5.0 <= info["navigator.connection.downlink"] <= 10.0
    assert info["navigator.connection.saveData"] is False
    
    # Test 3G profile
    info = generate_network_info('3g')
    assert info["navigator.connection.effectiveType"] == '3g'
    assert 100 <= info["navigator.connection.rtt"] <= 300
    assert 1.0 <= info["navigator.connection.downlink"] <= 3.0
    
    # Test random generation
    info = generate_network_info()
    assert info["navigator.connection.effectiveType"] in ['2g', '3g', '4g']


def test_generate_storage_quota():
    """Test storage quota generation"""
    quota = generate_storage_quota(0.5)
    assert quota["storage:quota:total"] >= 1024**3  # At least 1GB
    assert quota["storage:quota:usage"] <= quota["storage:quota:total"]
    assert quota["storage:quota:usage"] > 0


def test_generate_permissions_state():
    """Test permissions state generation"""
    # Default profile
    perms = generate_permissions_state('default')
    assert perms["permissions:state"]["geolocation"] == "prompt"
    assert perms["permissions:state"]["clipboard-write"] == "granted"
    
    # Permissive profile
    perms = generate_permissions_state('permissive')
    for perm in perms["permissions:state"].values():
        assert perm == "granted"
    
    # Restrictive profile
    perms = generate_permissions_state('restrictive')
    for perm in perms["permissions:state"].values():
        assert perm == "denied"


def test_enable_performance_fuzzing():
    """Test performance fuzzing configuration"""
    config = enable_performance_fuzzing(2.5)
    assert config["performance:timingFuzz"] is True
    assert config["performance:timingFuzz:maxJitter"] == 2.5


def test_enable_canvas_protection():
    """Test canvas protection configuration"""
    config = enable_canvas_protection(0.005, True)
    assert config["canvas:noise"] is True
    assert config["canvas:noiseLevel"] == 0.005
    assert config["canvas:textNoise"] is True
    assert 0.05 <= config["canvas:textNoiseLevel"] <= 0.2


def test_enable_scroll_humanization():
    """Test scroll humanization configuration"""
    config = enable_scroll_humanization(1.5)
    assert config["scroll:humanize"] is True
    assert 1.2 <= config["scroll:humanize:speed"] <= 1.8  # 1.5 * (0.8 to 1.2)
    assert 0.9 <= config["scroll:humanize:acceleration"] <= 1.1


def test_apply_advanced_antidetect():
    """Test applying all advanced anti-detection features"""
    config = {
        "navigator.userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    }
    
    apply_advanced_antidetect(config)
    
    # Check Client Hints were added
    assert "navigator.userAgentData.brands" in config
    assert "navigator.userAgentData.platform" in config
    
    # Check device APIs
    assert "navigator.deviceMemory" in config
    assert "navigator.connection.effectiveType" in config
    
    # Check canvas protection
    assert config.get("canvas:noise") is True
    
    # Check performance fuzzing
    assert config.get("performance:timingFuzz") is True
    
    # Check permissions
    assert "permissions:state" in config
    
    # Check storage quota
    assert "storage:quota:total" in config
    
    # Scroll should be disabled by default
    assert "scroll:humanize" not in config or config["scroll:humanize"] is False


def test_apply_advanced_antidetect_with_options():
    """Test selective feature enabling"""
    config = {}
    
    apply_advanced_antidetect(config,
        enable_client_hints=False,
        enable_device_apis=False,
        enable_canvas_protection=True,
        enable_timing_fuzzing=False,
        enable_scroll_humanization=True,
        enable_permissions=False,
        enable_storage_quota=False
    )
    
    # Only canvas and scroll should be enabled
    assert "navigator.userAgentData.brands" not in config
    assert "navigator.deviceMemory" not in config
    assert config.get("canvas:noise") is True
    assert config.get("performance:timingFuzz") is not True
    assert config.get("scroll:humanize") is True
    assert "permissions:state" not in config
    assert "storage:quota:total" not in config


if __name__ == "__main__":
    pytest.main([__file__, "-v"])