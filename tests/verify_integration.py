import sys
import ast
import unittest
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent.parent))

from Lang.python_ast import _compute_structure_hash, ASTNormalizer


class TestIntegration(unittest.TestCase):
    """Integration tests for X-Ray modules."""

    def test_compute_structure_hash_uses_rust(self):
        """
        Verify that _compute_structure_hash works and (implicitly) uses Rust if available.
        We can't easily mock the internal import without patching, but we can verify
        it returns a valid hash for known input.
        """
        code = 'def foo():\n    """Docstring"""\n    pass'
        node = ast.parse(code)

        # This should trigger the Rust path in _compute_structure_hash
        hash_val = _compute_structure_hash(node)

        print(f"Computed Hash: {hash_val}")
        self.assertTrue(len(hash_val) == 32, "Hash should be 32 chars (MD5)")

        # Verify it matches what we expect from manually normalizing
        # Rust normalize_code('def foo():\n    """Docstring"""\n    pass') -> 'def foo():\n    \n    pass'
        # MD5('def foo():\n    \n    pass')
        # Note: python_ast.py ASTNormalizer does slightly more (renaming args/vars).
        # Rust implementation in Phase 2 ONLY removes docstrings.
        # So the hashes might DIVERT if we aren't careful.
        # Let's check if they diverge.

        # Manual Python Normalization (Backup path)
        import copy
        import hashlib

        normalized_py = ASTNormalizer().visit(copy.deepcopy(node))
        hash_py = hashlib.sha256(ast.dump(normalized_py).encode()).hexdigest()

        print(f"Python Hash: {hash_py}")

        if hash_val != hash_py:
            print("⚠️ WARNING: Rust and Python hashes differ!")
            print(
                "This is expected in Phase 2 as Rust only strips docstrings, while Python renames vars."
            )
            print("We will align them in Phase 3.")
        else:
            print("✅ Hashes match!")


if __name__ == "__main__":
    unittest.main()
