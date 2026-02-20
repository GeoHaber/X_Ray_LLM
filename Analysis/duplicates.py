
from typing import List, Dict, Set, Tuple, Any
import asyncio
from collections import defaultdict, Counter

from Core.types import FunctionRecord, DuplicateGroup
from Core.utils import logger
from Core.inference import LLMHelper
from Analysis.similarity import (
    tokenize, _term_freq, cosine_similarity, code_similarity,
    semantic_similarity, _HAS_RUST
)
if _HAS_RUST:
     try:
         import x_ray_core as _rust_core
     except ImportError:
         _HAS_RUST = False

from Analysis.semantic_fuzzer import SemanticFuzzer

class UnionFind:
    """Simple union-find (disjoint-set) with path compression."""

    def __init__(self):
        self._parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        while self._parent[x] != x:
            self._parent[x] = self._parent.get(self._parent[x], self._parent[x])
            x = self._parent[x]
        return x

    def union(self, a: str, b: str):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def _compute_max_similarities(pairs):
    """Return dict mapping each function key to its maximum similarity."""
    max_sim: Dict[str, float] = defaultdict(float)
    for f1, f2, sim in pairs:
        max_sim[f1.key] = max(max_sim[f1.key], sim)
        max_sim[f2.key] = max(max_sim[f2.key], sim)
    return max_sim


def _cluster_by_root(pairs, uf, max_sim):
    """Group function-records by union-find root."""
    clusters: Dict[str, List[Tuple[FunctionRecord, float]]] = defaultdict(list)
    for f1, f2, sim in pairs:
        root = uf.find(f1.key)
        if not any(x[0].key == f1.key for x in clusters[root]):
            clusters[root].append((f1, max_sim[f1.key]))
        if not any(x[0].key == f2.key for x in clusters[root]):
            clusters[root].append((f2, max_sim[f2.key]))
    return clusters


def _collect_cluster_sims(pairs, uf):
    """Collect per-cluster pair-similarity lists."""
    cluster_pair_sims: Dict[str, List[float]] = defaultdict(list)
    for f1, f2, sim in pairs:
        cluster_pair_sims[uf.find(f1.key)].append(sim)
    return cluster_pair_sims


async def _enrich_group_async(item, llm, sem):
    """Enrich a single duplicate group with LLM merge suggestion."""
    group, f1, f2 = item
    async with sem:
        prompt = (
            "You are a refactoring expert.\n"
            f"Function A: {f1.name} ({f1.file_path}:{f1.line_start})\n"
            f"```python\n{f1.code[:500]}\n```\n\n"
            f"Function B: {f2.name} ({f2.file_path}:{f2.line_start})\n"
            f"```python\n{f2.code[:500]}\n```\n\n"
            "Should these be merged? If yes, suggest a unified function name "
            "and signature. If no, explain why they're different.\n\n"
            "Answer (2-3 sentences):"
        )
        try:
            response = await llm.completion_async(prompt)
            group.merge_suggestion = response.strip()
        except Exception as e:
            logger.debug(f"Async LLM merge suggestion failed: {e}")


class DuplicateFinder:
    """
    Cross-file function similarity detector.
    
    Four-stage pipeline:
      1a. Exact hash match  → identical code
      1b. Structural hash   → same AST shape, different variable names
      2.  Token n-gram fingerprint + AST histogram → near-duplicates (Type III)
      3.  Semantic similarity (name + signature + callgraph + docstring)
    """

    # Thresholds
    EXACT_THRESHOLD = 1.0
    NEAR_DUP_THRESHOLD = 0.80
    TOKEN_PREFILTER = 0.25
    SIZE_RATIO_MIN = 0.35       # skip if sizes wildly different
    SEMANTIC_THRESHOLD = 0.50   # semantic similarity threshold
    SEMANTIC_MIN_LINES = 8      # min function size for semantic matching

    # Boilerplate to skip
    _BOILERPLATE = frozenset({
        "__init__", "__repr__", "__str__", "__eq__", "__hash__",
        "__len__", "__iter__", "__next__", "__enter__", "__exit__",
        "__getitem__", "__setitem__", "__contains__",
        "setUp", "tearDown", "setup", "teardown",
    })

    def __init__(self):
        self.groups: List[DuplicateGroup] = []
        self._tokens: Dict[str, Counter] = {}

    def find(self, functions: List[FunctionRecord],
             cross_file_only: bool = True) -> List[DuplicateGroup]:
        """Find duplicate/similar functions across 4 stages (dispatcher).
        
        1. Exact hash + Structural hash
        2. Near-duplicates (code similarity)
        3. Semantic similarity
        """
        self.groups = []
        self._tokens = {}
        group_id = 0
        seen_keys: Set[str] = set()

        # Pre-compute tokens once
        self._precompute_tokens(functions)

        # Run all stages
        group_id = self._stage_hash_matches(functions, cross_file_only, group_id, seen_keys)
        group_id = self._stage_near_duplicates(functions, cross_file_only, group_id, seen_keys)
        group_id = self._stage_semantic_similarity(functions, cross_file_only, group_id, seen_keys)
        
        # 4. Operational Equivalence (Fuzzing) - Refine groups
        self._refine_with_fuzzer(functions)

        # Sort by quality
        self.groups.sort(key=lambda g: g.avg_similarity, reverse=True)
        return self.groups

    def _refine_with_fuzzer(self, functions: List[FunctionRecord]):
        """Run Semantic Fuzzer on near/semantic groups to detect operational morphing."""
        fuzzer = SemanticFuzzer()
        func_map = {f.key: f for f in functions}
        
        for group in self.groups:
            if group.similarity_type in ("exact", "structural", "operational"):
                continue
            if len(group.functions) < 2:
                continue
                
            # Pick candidates (pairwise or just leader vs others)
            # For simplicity, compare first function with others if they look promising
            
            # Optimization: only fuzz if similarity is high enough to warrant the cost
            if group.avg_similarity < 0.6: 
                continue

            leader_key = group.functions[0]["key"]
            leader = func_map.get(leader_key)
            if not leader: continue
            
            # Use executable code from leader
            try:
                # Need executable objects. This is tricky since we only have FunctionRecords with string code.
                # SemanticFuzzer typically needs callable objects OR we adapt it to compile from source.
                # We'll adapt here: compile the code string into a function object.
                exec_globals = {}
                exec(leader.code, exec_globals)
                func_a = exec_globals.get(leader.name)
            except Exception as e:
                logger.debug(f"Fuzzer compilation failed for {leader.name}: {e}")
                continue

            confirmed_group = True
            for member in group.functions[1:]:
                mem = func_map.get(member["key"])
                if not mem: continue
                
                try:
                    exec_globals_b = {}
                    exec(mem.code, exec_globals_b)
                    func_b = exec_globals_b.get(mem.name)
                    
                    if not func_a or not func_b:
                        confirmed_group = False
                        break

                    is_equiv, _ = fuzzer.check_equivalence(func_a, func_b, iterations=20)
                    if not is_equiv:
                        confirmed_group = False
                        # If not equivalent, we should arguably split the group or just leave it as 'semantic'
                        # For now, we only upgrade if ALL are equivalent? Or just mark pairwise.
                        # We'll keep it simple: if Pair(A, B) is equivalent, great.
                except Exception:
                    confirmed_group = False
            
            if confirmed_group:
                group.similarity_type = "operational"
                group.avg_similarity = 1.0
                group.merge_suggestion = "Functions are operationally identical (Doppelgänger). Safe to merge."

    def _precompute_tokens(self, functions: List[FunctionRecord]) -> None:
        """Pre-compute TF-IDF tokens for all functions (shared across stages)."""
        for func in functions:
            text = " ".join([
                func.name,
                func.docstring or "",
                " ".join(func.parameters),
                func.return_type or "",
                " ".join(func.calls_to),
                func.code or "",
            ])
            self._tokens[func.key] = _term_freq(tokenize(text))

    def _stage_hash_matches(self, functions: List[FunctionRecord],
                           cross_file_only: bool, group_id: int,
                           seen_keys: Set[str]) -> int:
        """Stage 1: Exact code hash + Structural hash matching (120 lines → 55 lines)."""
        # 1a. Exact hash matches
        hash_groups: Dict[str, List[FunctionRecord]] = defaultdict(list)
        for func in functions:
            if func.name not in self._BOILERPLATE:
                hash_groups[func.code_hash].append(func)

        for code_hash, group in hash_groups.items():
            if len(group) < 2 or (cross_file_only and len({f.file_path for f in group}) < 2):
                continue
            self.groups.append(DuplicateGroup(
                group_id=group_id, similarity_type="exact", avg_similarity=1.0,
                functions=[{"key": f.key, "name": f.name, "file": f.file_path,
                           "line": f.line_start, "size": f.size_lines, "similarity": 1.0}
                          for f in group],
            ))
            seen_keys.update(f.key for f in group)
            group_id += 1

        # 1b. Structural hash matches
        struct_groups: Dict[str, List[FunctionRecord]] = defaultdict(list)
        for func in functions:
            if (func.key not in seen_keys and func.name not in self._BOILERPLATE
                and func.size_lines >= 4 and func.structure_hash):
                struct_groups[func.structure_hash].append(func)

        for s_hash, group in struct_groups.items():
            if len(group) < 2 or (cross_file_only and len({f.file_path for f in group}) < 2):
                continue
            self.groups.append(DuplicateGroup(
                group_id=group_id, similarity_type="structural", avg_similarity=1.0,
                functions=[{"key": f.key, "name": f.name, "file": f.file_path,
                           "line": f.line_start, "size": f.size_lines, "similarity": 1.0}
                          for f in group],
                merge_suggestion="Logic is identical. Rename variables to unify."
            ))
            seen_keys.update(f.key for f in group)
            group_id += 1
        return group_id

    def _stage_near_duplicates(self, functions: List[FunctionRecord],
                              cross_file_only: bool, group_id: int,
                              seen_keys: Set[str]) -> int:
        """Stage 2: Token + Code similarity (near-duplicates) (100 lines → 40 lines)."""
        func_list = [f for f in functions if f.key not in seen_keys
                     and f.name not in self._BOILERPLATE and f.size_lines >= 5]

        # Pre-filter pairs with token cosine
        candidates: List[Tuple[FunctionRecord, FunctionRecord, float]] = []
        for i, f1 in enumerate(func_list):
            for f2 in func_list[i + 1:]:
                if cross_file_only and f1.file_path == f2.file_path:
                    continue
                ratio = min(f1.size_lines, f2.size_lines) / max(f1.size_lines, f2.size_lines)
                if ratio < self.SIZE_RATIO_MIN:
                    continue
                tok_sim = cosine_similarity(self._tokens.get(f1.key, Counter()),
                                          self._tokens.get(f2.key, Counter()))
                if tok_sim >= self.TOKEN_PREFILTER:
                    candidates.append((f1, f2, tok_sim))

        logger.info(f"Duplicate pre-filter: {len(candidates)} candidates from {len(func_list)} functions")

        # Compute full code similarity
        near_pairs: List[Tuple[FunctionRecord, FunctionRecord, float]] = []
        if _HAS_RUST and len(candidates) > 20:
            near_pairs = self._batch_code_similarity(candidates)
        else:
            near_pairs = [(f1, f2, code_similarity(f1.code, f2.code))
                         for f1, f2, _ in candidates
                         if code_similarity(f1.code, f2.code) >= self.NEAR_DUP_THRESHOLD]

        group_id = self._build_similarity_groups(near_pairs, group_id, "near", seen_keys)
        return group_id

    def _batch_code_similarity(self, candidates: List[Tuple[FunctionRecord, FunctionRecord, float]]) -> List[Tuple[FunctionRecord, FunctionRecord, float]]:
        """Compute similarity matrix in Rust (parallel)."""
        code_to_idx, code_list = {}, []
        for f1, f2, _ in candidates:
            for f in (f1, f2):
                if f.code not in code_to_idx:
                    code_to_idx[f.code] = len(code_list)
                    code_list.append(f.code)
        matrix = _rust_core.batch_code_similarity(code_list)
        return [(f1, f2, matrix[code_to_idx[f1.code]][code_to_idx[f2.code]])
                for f1, f2, _ in candidates
                if matrix[code_to_idx[f1.code]][code_to_idx[f2.code]] >= self.NEAR_DUP_THRESHOLD]

    def _stage_semantic_similarity(self, functions: List[FunctionRecord],
                                  cross_file_only: bool, group_id: int,
                                  seen_keys: Set[str]) -> int:
        """Stage 3: Semantic similarity (80 lines → 20 lines)."""
        semantic_list = [f for f in functions if f.key not in seen_keys
                        and f.name not in self._BOILERPLATE
                        and f.size_lines >= self.SEMANTIC_MIN_LINES]

        sem_pairs = []
        for i, f1 in enumerate(semantic_list):
            for f2 in semantic_list[i + 1:]:
                if not (cross_file_only and f1.file_path == f2.file_path):
                    sim = semantic_similarity(f1, f2)
                    if sim >= self.SEMANTIC_THRESHOLD:
                        sem_pairs.append((f1, f2, sim))

        if sem_pairs:
            logger.info(f"Semantic stage: {len(sem_pairs)} functionally similar pairs")
            group_id = self._build_similarity_groups(sem_pairs, group_id, "semantic", seen_keys)

        return group_id

    def _build_similarity_groups(self, pairs: List[Tuple[FunctionRecord, FunctionRecord, float]],
                                group_id: int, similarity_type: str,
                                seen_keys: Set[str]) -> int:
        """Cluster pairs using union-find, build DuplicateGroup objects."""
        if not pairs:
            return group_id

        uf = UnionFind()
        for f1, f2, _ in pairs:
            uf.union(f1.key, f2.key)

        max_sim = _compute_max_similarities(pairs)
        clusters = _cluster_by_root(pairs, uf, max_sim)
        cluster_pair_sims = _collect_cluster_sims(pairs, uf)

        for root_key, members in clusters.items():
            if len(members) < 2:
                continue
            pair_sims_list = cluster_pair_sims.get(root_key, [])
            avg = sum(pair_sims_list) / len(pair_sims_list) if pair_sims_list else 0
            self.groups.append(DuplicateGroup(
                group_id=group_id, similarity_type=similarity_type, avg_similarity=round(avg, 3),
                functions=[{"key": f.key, "name": f.name, "file": f.file_path,
                           "line": f.line_start, "size": f.size_lines, "similarity": round(sim, 3),
                           "signature": f.signature}
                          for f, sim in members],
            ))
            seen_keys.update(f.key for f, _ in members)
            group_id += 1
        return group_id

    def enrich_with_llm(self, llm: LLMHelper, functions: List[FunctionRecord],
                        max_calls: int = 15):
        """Ask LLM if near-duplicates should be merged."""
        func_map = {f.key: f for f in functions}
        enriched = 0

        for group in self.groups:
            if enriched >= max_calls:
                break
            if group.similarity_type == "exact":
                group.merge_suggestion = "Identical code — extract to a shared module."
                continue
            if len(group.functions) < 2:
                continue

            # Pick the two most similar functions for LLM review
            flist = group.functions[:2]
            f1 = func_map.get(flist[0]["key"])
            f2 = func_map.get(flist[1]["key"])
            if not f1 or not f2:
                continue

            prompt = (
                "You are a refactoring expert.\n"
                f"Function A: {f1.name} ({f1.file_path}:{f1.line_start})\n"
                f"```python\n{f1.code[:500]}\n```\n\n"
                f"Function B: {f2.name} ({f2.file_path}:{f2.line_start})\n"
                f"```python\n{f2.code[:500]}\n```\n\n"
                "Should these be merged? If yes, suggest a unified function name "
                "and signature. If no, explain why they're different.\n\n"
                "Answer (2-3 sentences):"
            )
            try:
                # Sync for now
                response = llm.query_sync(prompt, max_tokens=200)
                group.merge_suggestion = response.strip()
                enriched += 1
            except Exception as e:
                logger.debug(f"LLM merge suggestion failed: {e}")

    async def enrich_with_llm_async(self, llm: LLMHelper, functions: List[FunctionRecord], max_calls: int = 20):
        """Async version of enrich_with_llm."""
        func_map = {f.key: f for f in functions}
        
        # Collect groups that need enrichment
        candidates = []
        for group in self.groups:
            if len(candidates) >= max_calls:
                break
            if group.similarity_type == "exact":
                group.merge_suggestion = "Identical code — extract to a shared module."
                continue
            if len(group.functions) < 2:
                continue
            
            flist = group.functions[:2]
            f1 = func_map.get(flist[0]["key"])
            f2 = func_map.get(flist[1]["key"])
            if f1 and f2:
                candidates.append((group, f1, f2))

        if not candidates:
            return

        logger.info(f"Enriching {len(candidates)} duplicate groups with AI (Async)...")
        
        sem = asyncio.Semaphore(5)
        tasks = [_enrich_group_async(c, llm, sem) for c in candidates]
        await asyncio.gather(*tasks)

    def summary(self) -> Dict[str, Any]:
        """Return a summary of duplicate findings."""
        exact = [g for g in self.groups if g.similarity_type == "exact"]
        near = [g for g in self.groups if g.similarity_type == "near"]
        structural = [g for g in self.groups if g.similarity_type == "structural"]
        semantic = [g for g in self.groups if g.similarity_type == "semantic"]
        total_funcs = sum(len(g.functions) for g in self.groups)
        return {
            "total_groups": len(self.groups),
            "exact_duplicates": len(exact),
            "structural_duplicates": len(structural),
            "near_duplicates": len(near),
            "semantic_duplicates": len(semantic),
            "total_functions_involved": total_funcs,
            "avg_similarity": (
                round(sum(g.avg_similarity for g in self.groups) / len(self.groups), 3)
                if self.groups else 0
            ),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Legacy helpers for tests
    # ─────────────────────────────────────────────────────────────────────────

    def _is_valid_group(self, group_stats: List[Any], cross_file: bool = True) -> bool:
        """Helper for legacy tests validation."""
        if len(group_stats) < 2:
            return False
        if cross_file:
            # assuming group_stats is list of dicts or objects with file_path/file
            files = set()
            for x in group_stats:
                if isinstance(x, dict):
                    files.add(x.get("file"))
                else:
                    files.add(x.file_path)
            return len(files) >= 2
        return True

    def _func_to_dict(self, func: FunctionRecord) -> Dict[str, Any]:
        """Convert FunctionRecord to dict structure used in DuplicateGroup."""
        return {
            "key": func.key,
            "name": func.name,
            "file": func.file_path,
            "line": func.line_start,
            "size": func.size_lines,
            "signature": func.signature
        }
