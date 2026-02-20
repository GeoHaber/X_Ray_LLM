
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

    def check_equivalence(self, func_a: Callable, func_b: Callable, iterations: int = 50) -> Tuple[bool, str]:
        """
        Compare two functions by running them with diverse generated inputs.
        Returns (True, "") if they appear equivalent, or (False, reason).
        """
        # 1. Get Source Code for Input Generation
        # We need source to parse args. If unavailable, we can't generate inputs easily
        # (unless we fallback to inspection, which test_gen might not support fully yet)
        try:
            code_a = inspect.getsource(func_a)
        except OSError:
            return False, "Could not retrieve source code for func_a"

        # 2. Generate Inputs
        # We generate inputs based on func_a's signature. 
        # Requirement: func_b must accept the same inputs.
        inputs = self.generator.generate_inputs(code_a)
        
        # If generator returns static list, we might want to multiply/randomize it if it uses random internally
        # But TestGenerator._generate_numeric_cases returns fixed 4 cases per call.
        # Let's call it multiple times if we want more fuzzing, or assume TestGenerator logic improves.
        # For now, we trust the generator's diversity.
        
        if not inputs:
            return False, "Could not generate inputs for func_a"

        # 3. Generate Inputs
        all_inputs = []
        retries = 0
        # We try to generate enough inputs to meet 'iterations',
        # assuming the generator has some randomness.
        while len(all_inputs) < iterations and retries < 20:
            new_inputs = self.generator.generate_inputs(code_a)
            if not new_inputs: 
                break
            all_inputs.extend(new_inputs)
            retries += 1
        
        if not all_inputs:
            return False, "Could not generate inputs for func_a"

        # 4. Execution & Comparison
        for i, input_kwargs in enumerate(all_inputs[:iterations]):
            # Run A
            res_a, err_a = self._safe_execute(func_a, input_kwargs)
            
            # Run B
            res_b, err_b = self._safe_execute(func_b, input_kwargs)
            
            # Compare Exceptions
            if err_a or err_b:
                if type(err_a) != type(err_b):
                    return False, f"Exception mismatch on input {input_kwargs}: {type(err_a)} vs {type(err_b)}"
                # If both raised same exception type, we consider it a match (semantic equivalence includes error behavior)
                continue

            # Compare Results
            if res_a != res_b:
                return False, f"Result mismatch on input {input_kwargs}: {res_a} != {res_b}"

        return True, "Equivalent"

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
