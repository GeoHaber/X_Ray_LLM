import sys
import json
import unittest
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import Rust extension
try:
    from Core import x_ray_core
except ImportError:
    print(
        "❌ Critical: Could not import x_ray_core. Make sure it is compiled and in Core/"
    )
    sys.exit(1)


class TestRustASTVerification(unittest.TestCase):
    """Tests for Rust AST verification."""

    def setUp(self):
        self.fixtures_dir = Path(__file__).parent / "fixtures"

    def test_normalize_code_against_fixture(self):
        """Verify Rust normalize_code matches expected fixture output."""
        fixture_path = self.fixtures_dir / "python_normalize_wrapper_verification.json"

        if not fixture_path.exists():
            self.skipTest("Fixture not found. Run generate_ast_tests.py first.")

        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        print(f"\n🔍 Verifying {data['function']} against Rust implementation...")

        passed = 0
        for case in data["cases"]:
            if case.get("status") != "success":
                continue

            input_args = case["input"]["args"]
            # The fixture was generated for a wrapper, so the input is the first arg
            code_input = input_args[0]
            expected_output = case["output"]

            # Execute Rust function
            actual_output = x_ray_core.normalize_code(code_input)

            # Assert
            try:
                self.assertEqual(actual_output, expected_output)
                passed += 1
            except AssertionError as e:
                print(f"❌ Failed on input: {repr(code_input)}")
                print(f"   Expected: {repr(expected_output)}")
                print(f"   Actual:   {repr(actual_output)}")
                raise e

        print(f"✅ Verified {passed}/{len(data['cases'])} cases successfully.")


if __name__ == "__main__":
    unittest.main()
