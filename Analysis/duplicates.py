from typing import List, Dict, Set, Tuple, Any
import asyncio
from collections import defaultdict, Counter
from dataclasses import dataclass

from Core.types import FunctionRecord, DuplicateGroup
from Core.utils import logger
from Core.inference import LLMHelper, _llm_enrich_one
from Analysis.similarity import (
    tokenize,
    _term_freq,
    cosine_similarity,
    code_similarity,
    semantic_similarity,
    _HAS_RUST,
)

if _HAS_RUST:
    try:
        import x_ray_core as _rust_core

        if not hasattr(_rust_core, "prefilter_parallel"):
            _HAS_RUST = False
    except ImportError:
        _HAS_RUST = False

from Analysis.semantic_fuzzer import SemanticFuzzer


@dataclass
class _MatchContext:
    """Mutable state carried through hash-matching stages."""

    cross_file_only: bool
    group_id: int
    seen_keys: Set[str]


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
    await _llm_enrich_one(
        prompt,
        lambda resp: setattr(group, "merge_suggestion", resp),
        llm,
        sem,
    )


def _compile_to_callable(func_record: FunctionRecord, safe: bool = False):
    """Compile a FunctionRecord's code string into a callable, or None on failure."""
    if safe:
        # In safe mode, we don't execute code strings.
        return None
    try:
        exec_globals = {}
        # WARNING: exec is used for operational equivalence testing.
        # Only run on trusted codebases.
        exec(func_record.code, exec_globals)  # noqa: S102 # nosec B102
        return exec_globals.get(func_record.name)
    except Exception as e:
        logger.debug(f"Fuzzer compilation failed for {func_record.name}: {e}")
        return None


def _member_is_equivalent(leader_callable, member, func_map, fuzzer):
    """Check if a single group member is equivalent to the leader."""
    mem = func_map.get(member["key"])
    if not mem:
        return False
    func_b = _compile_to_callable(mem)
    if not leader_callable or not func_b:
        return False
    try:
        is_equiv, _ = fuzzer.check_equivalence(leader_callable, func_b, iterations=20)
        return is_equiv
    except Exception:
        return False


def _check_group_equivalence(leader_callable, group, func_map, fuzzer):
    """Check if all members of a group are operationally equivalent to the leader."""
    return all(
        _member_is_equivalent(leader_callable, member, func_map, fuzzer)
        for member in group.functions[1:]
    )


def _batch_code_similarity(candidates, threshold):
    """Compute similarity matrix in Rust (parallel)."""
    code_to_idx, code_list = {}, []
    for f1, f2, _ in candidates:
        for f in (f1, f2):
            if f.code not in code_to_idx:
                code_to_idx[f.code] = len(code_list)
                code_list.append(f.code)
    matrix = _rust_core.batch_code_similarity(code_list)
    return [
        (f1, f2, matrix[code_to_idx[f1.code]][code_to_idx[f2.code]])
        for f1, f2, _ in candidates
        if matrix[code_to_idx[f1.code]][code_to_idx[f2.code]] >= threshold
    ]


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
    SIZE_RATIO_MIN = 0.35  # skip if sizes wildly different
    SEMANTIC_THRESHOLD = 0.50  # semantic similarity threshold
    SEMANTIC_MIN_LINES = 8  # min function size for semantic matching

    # Boilerplate to skip
    _BOILERPLATE = frozenset(
        {
            "__init__",
            "__repr__",
            "__str__",
            "__eq__",
            "__hash__",
            "__len__",
            "__iter__",
            "__next__",
            "__enter__",
            "__exit__",
            "__getitem__",
            "__setitem__",
            "__contains__",
            "setUp",
            "tearDown",
            "setup",
            "teardown",
        }
    )

    def __init__(self):
        self.groups: List[DuplicateGroup] = []
        self._tokens: Dict[str, Counter] = {}

    def find(
        self, functions: List[FunctionRecord], cross_file_only: bool = True
    ) -> List[DuplicateGroup]:
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
        ctx = _MatchContext(
            cross_file_only=cross_file_only, group_id=group_id, seen_keys=seen_keys
        )
        self._stage_hash_matches(functions, ctx)
        group_id = ctx.group_id
        group_id = self._stage_near_duplicates(
            functions, cross_file_only, group_id, seen_keys
        )
        group_id = self._stage_semantic_similarity(
            functions, cross_file_only, group_id, seen_keys
        )

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
            if group.avg_similarity < 0.6:
                continue

            leader_key = group.functions[0]["key"]
            leader = func_map.get(leader_key)
            if not leader:
                continue

            func_a = _compile_to_callable(
                leader, safe=getattr(self, "safe_mode", False)
            )
            if not func_a:
                continue

            if _check_group_equivalence(func_a, group, func_map, fuzzer):
                group.similarity_type = "operational"
                group.avg_similarity = 1.0
                group.merge_suggestion = "Functions are operationally identical (Doppelgänger). Safe to merge."

    def _precompute_tokens(self, functions: List[FunctionRecord]) -> None:
        """Pre-compute TF-IDF tokens for all functions (shared across stages)."""
        for func in functions:
            text = " ".join(
                [
                    func.name,
                    func.docstring or "",
                    " ".join(func.parameters),
                    func.return_type or "",
                    " ".join(func.calls_to),
                    func.code or "",
                ]
            )
            self._tokens[func.key] = _term_freq(tokenize(text))

    def _build_dup_group(
        self,
        funcs: List[FunctionRecord],
        sim_type: str,
        group_id: int,
        seen_keys: Set[str],
        merge_msg: str = "",
    ) -> int:
        """Create a DuplicateGroup from a list of matched functions."""
        self.groups.append(
            DuplicateGroup(
                group_id=group_id,
                similarity_type=sim_type,
                avg_similarity=1.0,
                functions=[
                    {
                        "key": f.key,
                        "name": f.name,
                        "file": f.file_path,
                        "line": f.line_start,
                        "size": f.size_lines,
                        "similarity": 1.0,
                    }
                    for f in funcs
                ],
                merge_suggestion=merge_msg or None,
            )
        )
        seen_keys.update(f.key for f in funcs)
        return group_id + 1

    def _collect_hash_groups(
        self,
        functions: List[FunctionRecord],
        attr: str,
        seen_keys: Set[str],
        min_lines: int = 0,
    ) -> Dict[str, List[FunctionRecord]]:
        """Group functions by a hash attribute, filtering boilerplate and seen."""
        groups: Dict[str, List[FunctionRecord]] = defaultdict(list)
        for func in functions:
            if func.name in self._BOILERPLATE:
                continue
            if attr != "code_hash" and func.key in seen_keys:
                continue
            if func.size_lines < min_lines:
                continue
            hash_val = getattr(func, attr, None)
            if hash_val:
                groups[hash_val].append(func)
        return groups

    def _process_hash_group(
        self,
        groups: Dict[str, List[FunctionRecord]],
        ctx: _MatchContext,
        match_type: str,
        hint: str = "",
    ) -> None:
        """Build dup groups from hash-based groups."""
        for group in groups.values():
            if len(group) < 2:
                continue
            if ctx.cross_file_only and len({f.file_path for f in group}) < 2:
                continue
            ctx.group_id = self._build_dup_group(
                group, match_type, ctx.group_id, ctx.seen_keys, hint or None
            )

    def _stage_hash_matches(
        self, functions: List[FunctionRecord], ctx: _MatchContext
    ) -> None:
        """Stage 1: Exact code hash + Structural hash matching."""
        exact = self._collect_hash_groups(functions, "code_hash", ctx.seen_keys)
        self._process_hash_group(exact, ctx, "exact")

        structural = self._collect_hash_groups(
            functions, "structure_hash", ctx.seen_keys, min_lines=4
        )
        self._process_hash_group(
            structural,
            ctx,
            "structural",
            "Logic is identical. Rename variables to unify.",
        )

    def _prefilter_candidates(
        self, func_list: List[FunctionRecord], cross_file_only: bool
    ) -> List[Tuple[FunctionRecord, FunctionRecord, float]]:
        """Pre-filter function pairs by size ratio and token cosine."""
        candidates = []
        for i, f1 in enumerate(func_list):
            for f2 in func_list[i + 1 :]:
                if cross_file_only and f1.file_path == f2.file_path:
                    continue
                ratio = min(f1.size_lines, f2.size_lines) / max(
                    f1.size_lines, f2.size_lines
                )
                if ratio < self.SIZE_RATIO_MIN:
                    continue
                tok_sim = cosine_similarity(
                    self._tokens.get(f1.key, Counter()),
                    self._tokens.get(f2.key, Counter()),
                )
                if tok_sim >= self.TOKEN_PREFILTER:
                    candidates.append((f1, f2, tok_sim))
        return candidates

    def _stage_near_duplicates(
        self,
        functions: List[FunctionRecord],
        cross_file_only: bool,
        group_id: int,
        seen_keys: Set[str],
    ) -> int:
        """Stage 2: Token + Code similarity (near-duplicates)."""
        func_list = [
            f
            for f in functions
            if f.key not in seen_keys
            and f.name not in self._BOILERPLATE
            and f.size_lines >= 5
        ]

        if _HAS_RUST:
            # Returns (key1, key2, token_sim) — string keys, not objects
            raw_candidates = _rust_core.prefilter_parallel(
                func_list, self._tokens, cross_file_only,
                self.SIZE_RATIO_MIN, self.TOKEN_PREFILTER
            )
            logger.info(f"Duplicate pre-filter (Rust): {len(raw_candidates)} candidates")
            # Resolve string keys back to FunctionRecord objects
            func_map = {f.key: f for f in func_list}
            candidates = [
                (func_map[k1], func_map[k2], score)
                for k1, k2, score in raw_candidates
                if k1 in func_map and k2 in func_map
            ]
            near_pairs = _batch_code_similarity(candidates, self.NEAR_DUP_THRESHOLD)
        else:
            candidates = self._prefilter_candidates(func_list, cross_file_only)
            logger.info(f"Duplicate pre-filter (Python): {len(candidates)} candidates")
            near_pairs = [
                (f1, f2, code_similarity(f1.code, f2.code))
                for f1, f2, _ in candidates
                if code_similarity(f1.code, f2.code) >= self.NEAR_DUP_THRESHOLD
            ]

        group_id = self._build_similarity_groups(
            near_pairs, group_id, "near", seen_keys
        )
        return group_id

    def _stage_semantic_similarity(
        self,
        functions: List[FunctionRecord],
        cross_file_only: bool,
        group_id: int,
        seen_keys: Set[str],
    ) -> int:
        """Stage 3: Semantic similarity (80 lines → 20 lines)."""
        semantic_list = [
            f
            for f in functions
            if f.key not in seen_keys
            and f.name not in self._BOILERPLATE
            and f.size_lines >= self.SEMANTIC_MIN_LINES
        ]

        sem_pairs = []
        for i, f1 in enumerate(semantic_list):
            for f2 in semantic_list[i + 1 :]:
                if cross_file_only and f1.file_path == f2.file_path:
                    continue
                sim = semantic_similarity(f1, f2)
                if sim >= self.SEMANTIC_THRESHOLD:
                    sem_pairs.append((f1, f2, sim))

        if sem_pairs:
            logger.info(f"Semantic stage: {len(sem_pairs)} functionally similar pairs")
            group_id = self._build_similarity_groups(
                sem_pairs, group_id, "semantic", seen_keys
            )

        return group_id

    def _build_similarity_groups(
        self,
        pairs: List[Tuple[FunctionRecord, FunctionRecord, float]],
        group_id: int,
        similarity_type: str,
        seen_keys: Set[str],
    ) -> int:
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
            self.groups.append(
                DuplicateGroup(
                    group_id=group_id,
                    similarity_type=similarity_type,
                    avg_similarity=round(avg, 3),
                    functions=[
                        {
                            "key": f.key,
                            "name": f.name,
                            "file": f.file_path,
                            "line": f.line_start,
                            "size": f.size_lines,
                            "similarity": round(sim, 3),
                            "signature": f.signature,
                        }
                        for f, sim in members
                    ],
                )
            )
            seen_keys.update(f.key for f, _ in members)
            group_id += 1
        return group_id

    def enrich_with_llm(
        self, llm: LLMHelper, functions: List[FunctionRecord], max_calls: int = 15
    ):
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
                if self.groups
                else 0
            ),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Legacy helpers for tests
    # ─────────────────────────────────────────────────────────────────────────


async def enrich_with_llm_async(
    finder, llm: LLMHelper, functions: List[FunctionRecord], max_calls: int = 20
):
    """Async version of enrich_with_llm (module-level to reduce class size)."""
    func_map = {f.key: f for f in functions}
    candidates = []
    for group in finder.groups:
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


def _is_valid_group(group_stats: List[Any], cross_file: bool = True) -> bool:
    """Helper for legacy tests validation."""
    if len(group_stats) < 2:
        return False
    if cross_file:
        files = set()
        for x in group_stats:
            if isinstance(x, dict):
                files.add(x.get("file"))
            else:
                files.add(x.file_path)
        return len(files) >= 2
    return True


def _func_to_dict(func: FunctionRecord) -> Dict[str, Any]:
    """Convert FunctionRecord to dict structure used in DuplicateGroup."""
    return {
        "key": func.key,
        "name": func.name,
        "file": func.file_path,
        "line": func.line_start,
        "size": func.size_lines,
        "signature": func.signature,
    }
