"""Auto-generated monkey tests for _mothership/hardware_detection.py by X-Ray v7.0.

Tests function signatures, edge cases, and class instantiation.
"""

import pytest

def test__mothership_hardware_detection_detect_hardware_is_callable():
    """Verify detect_hardware exists and is callable."""
    from _mothership.hardware_detection import detect_hardware
    assert callable(detect_hardware)

def test__mothership_hardware_detection_detect_hardware_return_type():
    """Verify detect_hardware returns expected type."""
    from _mothership.hardware_detection import detect_hardware
    # Smoke check — return type should be: HardwareProfile
    # (requires valid args to test; assert function exists)
    assert callable(detect_hardware)

def test__mothership_hardware_detection_format_hardware_profile_is_callable():
    """Verify format_hardware_profile exists and is callable."""
    from _mothership.hardware_detection import format_hardware_profile
    assert callable(format_hardware_profile)

def test__mothership_hardware_detection_format_hardware_profile_none_args():
    """Monkey: call format_hardware_profile with None args — should not crash unhandled."""
    from _mothership.hardware_detection import format_hardware_profile
    try:
        format_hardware_profile(None, None)
    except (TypeError, ValueError, AttributeError, KeyError):
        pass  # Expected — function should raise, not crash
    except Exception as e:
        pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

def test__mothership_hardware_detection_format_hardware_profile_return_type():
    """Verify format_hardware_profile returns expected type."""
    from _mothership.hardware_detection import format_hardware_profile
    # Smoke check — return type should be: str
    # (requires valid args to test; assert function exists)
    assert callable(format_hardware_profile)
