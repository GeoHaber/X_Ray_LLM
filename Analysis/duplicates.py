
from typing import List, Dict, Set, Tuple
from collections import defaultdict, Counter
from difflib import SequenceMatcher

from Core.types import FunctionRecord, DuplicateGroup
from Core.utils import logger
from Lang.tokenizer import tokenize, term_freq, cosine_similarity

class DuplicateFinder:
    """Finds exact, structural, and near-duplicate functions."""
    
    NEAR_DUP_THRESHOLD = 0.70
    TOKEN_PREFILTER = 0.25
    SIZE_RATIO_MIN = 0.35
    _BOILERPLATE = frozenset({
        "__init__", "__repr__", "__str__", "__eq__", "__hash__",
        "__len__", "__iter__", "__next__", "__enter__", "__exit__",
    })

    def __init__(self):
        self.groups: List[DuplicateGroup] = []
        self._tokens: Dict[str, Counter] = {}

    def find(self, functions: List[FunctionRecord], cross_file_only: bool = True) -> List[DuplicateGroup]:
        self.groups = []
        group_id = 0

        # Pre-compute tokens
        for func in functions:
            text = f"{func.name} {func.docstring or ''} {' '.join(func.parameters)} {func.code}"
            self._tokens[func.key] = term_freq(tokenize(text))

        # 1. Exact Code Hash
        hash_groups = defaultdict(list)
        for func in functions:
            if func.name not in self._BOILERPLATE:
                hash_groups[func.code_hash].append(func)
        
        seen_keys = set()
        for group in hash_groups.values():
            if self._is_valid_group(group, cross_file_only):
                self.groups.append(DuplicateGroup(
                    group_id=group_id, similarity_type="exact", avg_similarity=1.0,
                    functions=[self._func_to_dict(f) for f in group]
                ))
                seen_keys.update(f.key for f in group)
                group_id += 1

        # 1.5 Structural Hash
        struct_groups = defaultdict(list)
        for func in functions:
            if func.key not in seen_keys and func.name not in self._BOILERPLATE:
                 if func.size_lines >= 4 and func.structure_hash:
                     struct_groups[func.structure_hash].append(func)
        
        for group in struct_groups.values():
            if self._is_valid_group(group, cross_file_only):
                self.groups.append(DuplicateGroup(
                    group_id=group_id, similarity_type="structural", avg_similarity=1.0,
                    functions=[self._func_to_dict(f) for f in group],
                    merge_suggestion="Logic is identical. Rename variables to unify."
                ))
                seen_keys.update(f.key for f in group)
                group_id += 1

        return self.groups

    def _is_valid_group(self, group: List[FunctionRecord], cross_file: bool) -> bool:
        if len(group) < 2: return False
        if cross_file:
            return len({f.file_path for f in group}) >= 2
        return True

    def _func_to_dict(self, f: FunctionRecord):
        return {"key": f.key, "name": f.name, "file": f.file_path, "line": f.line_start}
