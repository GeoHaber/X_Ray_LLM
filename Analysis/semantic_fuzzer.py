
import inspect
from typing import Callable, Any, Dict, List, Tuple, Optional
from .test_gen import TestGenerator

class SemanticFuzzer:
    """
    detects 'Doppelgänger' functions: structurally different but functionally identical.
    Uses differential fuzzing (generative testing) to verify operational equivalence.
    """
    
    def __init__(self):
        self.generator = TestGenerator()

    def _gather_inputs(self, func_a: Callable, iterations: int):
        """Generate diverse inputs for *func_a* up to *iterations* count.
        
        Returns a list of input-kwarg dicts, or None if generation fails.
        """
        try:
            code_a = inspect.getsource(func_a)
        except OSError:
            return None

        all_inputs = []
        retries = 0
        while len(all_inputs) < iterations and retries < 20:
            new_inputs = self.generator.generate_inputs(code_a)
            if not new_inputs:
                break
            all_inputs.extend(new_inputs)
            retries += 1
        return all_inputs or None

    def _compare_executions(self, func_a, func_b, inputs, iterations):
        """Run both functions on *inputs* and check for mismatches.
        
        Returns (True, "") if equivalent, (False, reason) otherwise.
        """
        for input_kwargs in inputs[:iterations]:
            res_a, err_a = self._safe_execute(func_a, input_kwargs)
            res_b, err_b = self._safe_execute(func_b, input_kwargs)

            if err_a or err_b:
                if not isinstance(err_a, type(err_b)):
                    return False, (f"Exception mismatch on input {input_kwargs}: "
                                   f"{type(err_a)} vs {type(err_b)}")
                continue

            if res_a != res_b:
                return False, f"Result mismatch on input {input_kwargs}: {res_a} != {res_b}"

        return True, "Equivalent"

    def check_equivalence(self, func_a: Callable, func_b: Callable, iterations: int = 50) -> Tuple[bool, str]:
        """
        Compare two functions by running them with diverse generated inputs.
        Returns (True, "") if they appear equivalent, or (False, reason).
        """
        all_inputs = self._gather_inputs(func_a, iterations)
        if all_inputs is None:
            return False, "Could not generate inputs for func_a"
        return self._compare_executions(func_a, func_b, all_inputs, iterations)

    def _safe_execute(self, func: Callable, kwargs: Dict[str, Any]) -> Tuple[Any, Optional[Exception]]:
        """Run function and capture result or exception."""
        try:
            return func(**kwargs), None
        except Exception as e:
            return None, e

    def fuzz_functions(self, functions: List[Callable]) -> List[Tuple[str, str]]:
        """
        Pairwise compare a list of functions. 
        Returns list of (name1, name2) tuples that are equivalent.
        """
        duplicates = []
        n = len(functions)
        for i in range(n):
            for j in range(i + 1, n):
                f1 = functions[i]
                f2 = functions[j]
                # Optimization: only compare if signatures allow (arg count match)
                # But for now, check_equivalence will fail safely if args mismatch (TypeError)
                
                is_equiv, _ = self.check_equivalence(f1, f2)
                if is_equiv:
                    duplicates.append((f1.__name__, f2.__name__))
        return duplicates
