import unittest
from Analysis.semantic_fuzzer import SemanticFuzzer

# Sample Functions for Testing


def mul_2(x, y):
    return x * 2


def shift_1(x, y):
    # Functionally equivalent to x * 2 for integers, but signature matches mul_2 (unused y)
    return x << 1


def add_self(x, y):
    return x + x


def distinct_op(x, y):
    return x + 5


def buggy_mul(x, y):
    if x % 5 == 0:
        return 0
    return x * 2


# Complex morphing
def complex_A(a, b):
    # (a + b)^2
    return (a + b) ** 2


def complex_B(a, b):
    # a^2 + 2ab + b^2
    return a**2 + 2 * a * b + b**2


class TestSemanticFuzzer(unittest.TestCase):
    def setUp(self):
        self.fuzzer = SemanticFuzzer()

    def test_identity(self):
        """A function should be equivalent to itself."""
        equiv, _ = self.fuzzer.check_equivalence(mul_2, mul_2)
        self.assertTrue(equiv, "Identity check failed")

    def test_operational_morphing_simple(self):
        """Detect x*2 == x<<1 == x+x"""
        # Note: TestGenerator treats 'x', 'y' as numeric args.
        # We need to ensure generated inputs don't trigger type errors for bitshift if generator uses floats?
        # Analysis/test_gen.py _generate_numeric_cases uses randint/ints, so bitshift is safe.

        equiv, reason = self.fuzzer.check_equivalence(mul_2, shift_1)
        self.assertTrue(equiv, f"Failed to detect shift optimization: {reason}")

        equiv, reason = self.fuzzer.check_equivalence(mul_2, add_self)
        self.assertTrue(equiv, f"Failed to detect add_self optimization: {reason}")

    def test_algebraic_expansion(self):
        """Detect (a+b)^2 == a^2 + 2ab + b^2"""
        equiv, reason = self.fuzzer.check_equivalence(complex_A, complex_B)
        self.assertTrue(equiv, f"Failed to verify algebraic identity: {reason}")

    def test_distinct_functions(self):
        """Detect x*2 != x+5"""
        equiv, _ = self.fuzzer.check_equivalence(mul_2, distinct_op)
        self.assertFalse(equiv, "Incorrectly flagged distinct functions as equivalent")

    def test_bug_detection(self):
        """Detect hidden bug/inequivalence"""
        equiv, reason = self.fuzzer.check_equivalence(mul_2, buggy_mul)
        self.assertFalse(equiv, "Failed to detect bug at input=10")


if __name__ == "__main__":
    unittest.main()
