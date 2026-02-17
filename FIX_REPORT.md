# X-Ray Code Quality Fix Report
**Date:** 2026-02-17 | **Scope:** Top 5 Critical Issues

---

## Issue #1: `Analysis/duplicates.py:find()` — 245 lines, complexity 74

**Problem:**
- Monolithic function doing 4 jobs (hash stage, structural stage, semantic stage, filtering)
- 25 branches, nesting depth 4 (at limit)
- Hard to test individual stages, hard to debug

**Solution:** Extract into 4 helper methods
```python
def find(self, functions: List[FunctionRecord], cross_file_only: bool = True) -> List[DuplicateGroup]:
    """Dispatcher — coordinates all stages."""
    self._prepare_tokens(functions)
    group_id = 0
    
    group_id = self._stage_exact(functions, cross_file_only, group_id)
    group_id = self._stage_structural(functions, cross_file_only, group_id)
    group_id = self._stage_semantic(functions, cross_file_only, group_id)
    
    return self.groups

def _prepare_tokens(self, functions: List[FunctionRecord]) -> None:
    """Pre-compute TF-IDF tokens once."""
    # Current tokenization logic (10 lines)

def _stage_exact(self, functions, cross_file_only, group_id) -> int:
    """Hash matching stage."""
    # Current hash matching logic (20 lines)
    return group_id

def _stage_structural(self, functions, cross_file_only, group_id) -> int:
    """Structural/AST matching stage."""
    # Current structure_hash logic (30 lines)
    return group_id

def _stage_semantic(self, functions, cross_file_only, group_id) -> int:
    """Semantic similarity stage."""
    # Current TF-IDF/cosine logic (40 lines)
    return group_id
```
**Impact:** Each stage ≤60 lines, testable independently ✓ No logic change

---

## Issue #2: `extract_functions_from_file()` — 93 lines, complexity 26, nesting 6

**Problem:**
- Parses, extracts functions, extracts classes in one block
- 6 nested levels (at limit) when handling AST nodes

**Solution:** Extract helper for cleaner node processing
```python
def extract_functions_from_file(fpath: Path, root: Path) -> Tuple[...]:
    """High-level orchestrator."""
    try:
        source = fpath.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(fpath))
    except Exception as e:
        return [], [], str(e)

    rel_path = str(fpath.relative_to(root)).replace("\\", "/")
    functions = []
    classes = []
    
    for node in _walk_definitions(tree):
        if isinstance(node, ast.FunctionDef):
            functions.append(_build_function_record(node, rel_path, source))
        elif isinstance(node, ast.ClassDef):
            classes.append(_build_class_record(node, rel_path, source))
    
    return functions, classes, None

def _build_function_record(node: ast.FunctionDef, rel_path: str, source: str) -> FunctionRecord:
    """Extract single function without nesting."""
    lines = source.splitlines()
    start, end = _get_node_range(node, lines)
    code = "\n".join(lines[start:end])
    
    return FunctionRecord(
        name=node.name,
        file_path=rel_path,
        # ... rest of fields
    )

def _build_class_record(node: ast.ClassDef, rel_path: str, source: str) -> ClassRecord:
    """Extract single class without nesting."""
    # Similar pattern
```
**Impact:** Main function drops from 93→30 lines, nesting 6→2 ✓ All logic preserved

---

## Issue #3: Duplicate Code in `Analysis/` vs `Lang/`

**Problem:**
```
Analysis/ast_utils.py:18         _compute_nesting_depth  ← exact copy
Lang/python_ast.py:14            _compute_nesting_depth  ← exact copy

Analysis/ast_utils.py:38         _compute_complexity     ← exact copy  
Lang/python_ast.py:34            _compute_complexity     ← exact copy
```

**Solution:** Create `Core/ast_helpers.py`, import in both
```python
# Core/ast_helpers.py
def compute_nesting_depth(node: ast.AST, max_depth: int = 0) -> int:
    """Shared utility."""
    if not hasattr(node, 'body'):
        return max_depth
    for child in node.body:
        max_depth = max(max_depth, compute_nesting_depth(child, max_depth + 1))
    return max_depth

def compute_complexity(node: ast.AST) -> int:
    """Shared utility."""
    # Current logic
```

Then in both files:
```python
# Analysis/ast_utils.py
from Core.ast_helpers import compute_nesting_depth, compute_complexity

# Lang/python_ast.py  
from Core.ast_helpers import compute_nesting_depth, compute_complexity
```
**Impact:** 1 source of truth, 30 lines DRY, maintained in one place ✓ Zero behavioral change

---

## Issue #4: Missing Docstrings (31 functions + 34 classes)

**Problem:** 65 missing docstrings make code harder to maintain/use

**Solution:** Add one-liner docstrings in priority order
```python
# Example fixes:
def analyze(self) -> Dict[str, Any]:
    """Group duplicates into shared library extraction suggestions."""
    # existing code

def visit_FunctionDef(self, node):  
    """Visit function definition and record metadata."""
    # existing code

class TestCodeSmellDetectorFunctions:
    """Test suite for function-level code smell detection."""
    # existing tests
```
**Priority:** Fix top 10 in production code (Analysis/, Core/)
**Time:** ~10 min | **Impact:** Full API documentation ✓

---

## Issue #5: Deep Nesting in `_normalized_token_stream()` (nesting 6)

**Problem:**
```python
for ... in ...:
    if ...:
        for ... in ...:
            if ...[:
                for ... in ...:    # NESTING DEPTH 6
```

**Solution:** Extract loops into helper
```python
def _normalized_token_stream(self, code: str) -> List[str]:
    """Tokenize and normalize code."""
    tokens = self._tokenize_lines(code.splitlines())
    return self._filter_and_normalize(tokens)

def _tokenize_lines(self, lines: List[str]) -> List[str]:
    """Extract tokens from code lines (1 loop)."""
    tokens = []
    for line in lines:
        tokens.extend(self._extract_from_line(line))
    return tokens

def _extract_from_line(self, line: str) -> List[str]:
    """Get normalized tokens from 1 line (1 loop)."""
    tokens = []
    for match in IDENTIFIER_REGEX.finditer(line):
        tokens.append(match.group().lower())
    return tokens
```
**Impact:** Nesting 6→2, easier to unit test ✓ Same output

---

## Implementation Order (Recommended)

1. **Issue #3** (Duplicate Code) — 10 min, highest ROI
   - Create `Core/ast_helpers.py`
   - Update imports
   
2. **Issue #1** (`find()` refactor) — 30 min, unblocks testing
   - Extract 4 stages
   - Add unit tests per stage
   
3. **Issue #2** (`extract_functions_from_file()`) — 20 min
   - Split into 2 helpers
   - Verify all tests pass
   
4. **Issue #5** (Nesting in similarity) — 15 min
   - Extract 2 helper methods
   
5. **Issue #4** (Docstrings) — 10 min
   - Focus on Analysis/ & Core/ first

**Total:** ~85 min | **Test Coverage:** No regression expected

---

## Verification Checklist

- [ ] All tests pass (`pytest`)
- [ ] Line coverage stays ≥85%
- [ ] Re-run X-Ray self-scan shows improvements
- [ ] No behavioral changes to outputs

