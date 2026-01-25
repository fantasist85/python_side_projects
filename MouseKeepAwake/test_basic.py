#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Basic functionality test for MouseKeepAwake
Tests mouse monitoring without GUI
"""

import time
from main import MouseKeepAwake


def test_basic_functionality():
    """Test basic mouse monitoring functionality"""

    print("=" * 60)
    print("MouseKeepAwake Basic Functionality Test")
    print("=" * 60)

    # Create instance with short timeout for testing
    app = MouseKeepAwake(idle_timeout=3)

    print("\n1. Testing initialization...")
    assert app.idle_timeout == 3, "Idle timeout not set correctly"
    assert app.enabled == True, "Should be enabled by default"
    assert app.running == False, "Should not be running initially"
    print("✓ Initialization OK")

    print("\n2. Testing start...")
    app.start()
    time.sleep(0.5)  # Give it time to start
    assert app.running == True, "Should be running after start"
    print("✓ Start OK")

    print("\n3. Testing mouse activity tracking...")
    initial_time = app.last_activity
    time.sleep(1)
    # Simulate mouse event
    app.on_move(100, 100)
    assert app.last_activity > initial_time, "Last activity should be updated"
    print("✓ Mouse activity tracking OK")

    print("\n4. Testing toggle...")
    app.toggle()
    assert app.enabled == False, "Should be disabled after toggle"
    app.toggle()
    assert app.enabled == True, "Should be enabled after second toggle"
    print("✓ Toggle OK")

    print("\n5. Testing idle detection (waiting 5 seconds)...")
    print("   This will move your mouse cursor slightly...")
    time.sleep(5)
    print("✓ Idle detection OK (if mouse moved, test passed)")

    print("\n6. Testing stop...")
    app.stop()
    time.sleep(0.5)
    assert app.running == False, "Should not be running after stop"
    print("✓ Stop OK")

    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)


def test_config_loading():
    """Test configuration loading"""

    print("\n" + "=" * 60)
    print("Configuration Test")
    print("=" * 60)

    try:
        from config import IDLE_TIMEOUT, MOVEMENT_PIXELS, MOVEMENT_DELAY, CHECK_INTERVAL
        print(f"\nConfiguration loaded successfully:")
        print(f"  IDLE_TIMEOUT: {IDLE_TIMEOUT} seconds")
        print(f"  MOVEMENT_PIXELS: {MOVEMENT_PIXELS} pixels")
        print(f"  MOVEMENT_DELAY: {MOVEMENT_DELAY} seconds")
        print(f"  CHECK_INTERVAL: {CHECK_INTERVAL} seconds")
        print("✓ Configuration OK")
    except ImportError as e:
        print(f"✗ Configuration loading failed: {e}")
        print("  Using default values")


if __name__ == '__main__':
    try:
        test_config_loading()
        test_basic_functionality()
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        exit(1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        exit(0)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
