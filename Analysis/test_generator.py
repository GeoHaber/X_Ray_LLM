"""Re-export TestGeneratorEngine from its current location.

The engine class lives in tests/test_generator.py (historical placement).
This shim keeps ``from Analysis.test_generator import TestGeneratorEngine``
working so Core/scan_phases.py resolves correctly.
"""

from tests.test_generator import (  # noqa: F401
    GeneratedTestFile,
    TestGenReport,
    TestGeneratorEngine,
)

__all__ = ["TestGeneratorEngine", "TestGenReport", "GeneratedTestFile"]
