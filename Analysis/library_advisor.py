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

    def analyze(
        self, duplicates: List[DuplicateGroup], functions: List[FunctionRecord]
    ) -> List[LibrarySuggestion]:
        """Analyze duplicates and cross-file name repetition for library candidates."""
        self.suggestions = []
        self._analyzed_count = len(functions)
        self._from_duplicates(duplicates)
        self._from_name_repetition(functions)
        return self.suggestions

    # -- private helpers (extracted from analyze) ----------------------------

    def _from_duplicates(self, duplicates: List[DuplicateGroup]) -> None:
        """Create suggestions from explicit duplicate groups."""
        for group in duplicates:
            if len(group.functions) < 2 and group.similarity_type != "exact":
                continue
            names = [f["name"] for f in group.functions]
            most_common_name = max(set(names), key=names.count)
            module_name = self._suggest_module_name([most_common_name])
            self.suggestions.append(
                LibrarySuggestion(
                    module_name=module_name,
                    description=f"Cluster of {len(group.functions)} similar functions ({most_common_name})",
                    functions=group.functions,
                    unified_api=f"def {most_common_name}(...):",
                    rationale=f"Found {len(group.functions)} {group.similarity_type} duplicates.",
                )
            )

    @staticmethod
    def _is_dunder(name: str) -> bool:
        return name.startswith("__") and name.endswith("__")

    def _is_cross_file_candidate(
        self, name: str, funcs: List[FunctionRecord], covered_keys: set
    ) -> bool:
        """Check if a group of same-named functions qualifies for suggestion."""
        if len(funcs) < 2:
            return False
        files = {f.file_path for f in funcs}
        return len(files) >= 2 and not any(f.key in covered_keys for f in funcs)

    def _from_name_repetition(self, functions: List[FunctionRecord]) -> None:
        """Create suggestions from cross-file name repetition."""
        name_map: Dict[str, List[FunctionRecord]] = defaultdict(list)
        for f in functions:
            if not self._is_dunder(f.name):
                name_map[f.name].append(f)

        covered_keys = {f.get("key") for s in self.suggestions for f in s.functions}

        for name, funcs in name_map.items():
            if not self._is_cross_file_candidate(name, funcs, covered_keys):
                continue
            module_name = self._suggest_module_name([name])
            func_dicts = [
                {
                    "name": f.name,
                    "file": f.file_path,
                    "line": f.line_start,
                    "key": f.key,
                }
                for f in funcs
            ]
            files = {f.file_path for f in funcs}
            self.suggestions.append(
                LibrarySuggestion(
                    module_name=module_name,
                    description=f"Multiple functions named '{name}' across {len(files)} files",
                    functions=func_dicts,
                    unified_api=f"def {name}(...):",
                    rationale="Identical naming suggests shared concept.",
                )
            )

    _MODULE_KEYWORDS = [
        (("parse",), "utils"),
        (("read", "write", "load"), "io_helpers"),
        (("validate", "check"), "validators"),
        (("search", "find"), "search"),
    ]

    def _suggest_module_name(self, func_names: List[str]) -> str:
        """Heuristic to name the module based on function names."""
        name = func_names[0].lower()
        for keywords, module in self._MODULE_KEYWORDS:
            if any(kw in name for kw in keywords):
                return module
        return "shared_utils"

    def summary(self) -> Dict[str, Any]:
        return {
            "total_suggestions": len(self.suggestions),
            "total_functions": self._analyzed_count,
            "modules_proposed": sorted(
                list(set(s.module_name for s in self.suggestions))
            ),
        }


# Module-level API for test compatibility
_default_analyzer = LibraryAdvisor()


def analyze(duplicates, functions):
    """Wrapper for LibraryAdvisor.analyze()."""
    return _default_analyzer.analyze(duplicates, functions)


def summary():
    """Wrapper for LibraryAdvisor.summary()."""
    return _default_analyzer.summary()
