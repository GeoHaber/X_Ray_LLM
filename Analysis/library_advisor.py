
from typing import List, Dict, Any
from collections import defaultdict
from Core.types import FunctionRecord, DuplicateGroup, LibrarySuggestion

class LibraryAdvisor:
    """
    Analyzes duplication groups and function names to suggest potential shared libraries.
    """
    def __init__(self):
        self.suggestions: List[LibrarySuggestion] = []
        self._analyzed_count = 0

    def analyze(self, duplicates: List[DuplicateGroup], functions: List[FunctionRecord]) -> List[LibrarySuggestion]:
        self.suggestions = []
        self._analyzed_count = len(functions)
        
        # 1. Suggestions from explicit duplicates
        for group in duplicates:
            # Only suggest for substantial groups
            if len(group.functions) < 2 and group.similarity_type != "exact":
                continue
            
            names = [f["name"] for f in group.functions]
            most_common_name = max(set(names), key=names.count)
            module_name = self._suggest_module_name([most_common_name])
            
            sug = LibrarySuggestion(
                module_name=module_name,
                description=f"Cluster of {len(group.functions)} similar functions ({most_common_name})",
                functions=group.functions,
                unified_api=f"def {most_common_name}(...):",
                rationale=f"Found {len(group.functions)} {group.similarity_type} duplicates."
            )
            self.suggestions.append(sug)

        # 2. Suggestions from cross-file name repetition (if not already covered)
        # Group functions by name (skip dunder/boilerplate methods)
        name_map = defaultdict(list)
        for f in functions:
            if f.name.startswith("__") and f.name.endswith("__"):
                continue  # skip dunder methods like __init__, __repr__, etc.
            name_map[f.name].append(f)
            
        covered_keys = set()
        for s in self.suggestions:
            for f in s.functions:
                covered_keys.add(f.get("key")) # duplicate dicts have 'key'

        for name, funcs in name_map.items():
            if len(funcs) < 2: 
                continue
            
            # Check if they inhabit different files
            files = {f.file_path for f in funcs}
            if len(files) < 2:
                continue

            # Check if already covered by duplicates
            # (Simplification: if any function is covered, skip)
            if any(f.key in covered_keys for f in funcs):
                continue
                
            module_name = self._suggest_module_name([name])
            
            # Convert FunctionRecord to dict for consistent API
            func_dicts = [
                {"name": f.name, "file": f.file_path, "line": f.line_start, "key": f.key}
                for f in funcs
            ]
            
            sug = LibrarySuggestion(
                module_name=module_name,
                description=f"Multiple functions named '{name}' across {len(files)} files",
                functions=func_dicts,
                unified_api=f"def {name}(...):",
                rationale="Identical naming suggests shared concept."
            )
            self.suggestions.append(sug)
            
        return self.suggestions

    def _suggest_module_name(self, func_names: List[str]) -> str:
        """Heuristic to name the module based on function names."""
        name = func_names[0].lower()
        if "parse" in name:
            return "utils"
        if "read" in name or "write" in name or "load" in name:
            return "io_helpers"
        if "validate" in name or "check" in name:
            return "validators"
        if "search" in name or "find" in name:
            return "search"
        return "shared_utils"

    def summary(self) -> Dict[str, Any]:
        return {
            "total_suggestions": len(self.suggestions),
            "total_functions": self._analyzed_count,
            "modules_proposed": sorted(list(set(s.module_name for s in self.suggestions)))
        }
