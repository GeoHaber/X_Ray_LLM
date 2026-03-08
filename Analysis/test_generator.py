"""Re-export TestGeneratorEngine from its current location.

The engine class lives in tests/test_generator.py (historical placement).
This shim keeps ``from Analysis.test_generator import TestGeneratorEngine``
working so Core/scan_phases.py resolves correctly.
"""

from tests.test_generator import (  # noqa: F401
    GeneratedTestFile,
    JSTSTestGenerator,
    PythonTestGenerator,
    TestGenReport,
    TestGeneratorEngine,
    _group_by_file,
    _guess_import_path,
    _is_test_file,
    _module_from_filepath,
    _safe_identifier,
)

__all__ = [
    "GeneratedTestFile",
    "JSTSTestGenerator",
    "PythonTestGenerator",
    "TestGenReport",
    "TestGeneratorEngine",
    "_group_by_file",
    "_guess_import_path",
    "_is_test_file",
    "_module_from_filepath",
    "_safe_identifier",
]
