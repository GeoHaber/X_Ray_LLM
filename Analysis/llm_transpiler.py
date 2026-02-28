"""
Analysis/llm_transpiler.py — LLM-Powered Python → Rust Transpiler
====================================================================

Hybrid fallback engine: when the AST-based transpiler in ``transpiler.py``
produces ``todo!()`` stubs (because the Python code is too complex for
deterministic tree-walking), this module hands the function to a local LLM
(via ``Core.inference.LLMHelper``) and asks it to produce valid Rust.

The result is then validated with ``rustc --edition 2021 --check`` so we
never emit broken code.  If the LLM fails or the compiler rejects the
output, we fall back to the original ``todo!()`` stub — always safe.

Architecture
------------
::

    transpile_function_code()          (AST — fast, deterministic)
        │
        ├─ result is real Rust  ──→  keep it  ✅
        │
        └─ result has todo!()  ──→  llm_transpile_function()
                                         │
                                         ├─ LLM available?  No ──→ keep todo!()
                                         │
                                         ├─ LLM produces Rust
                                         │      │
                                         │      ├─ rustc --check passes ──→ use it ✅
                                         │      │
                                         │      └─ rustc rejects ──→ retry once
                                         │             │
                                         │             ├─ pass ──→ use it ✅
                                         │             └─ fail ──→ keep todo!()
                                         │
                                         └─ LLM errors out ──→ keep todo!()

Usage
-----
::

    from Analysis.llm_transpiler import hybrid_transpile, LLMTranspiler

    # One-shot: try AST first, fall back to LLM
    rust = hybrid_transpile(python_code, name_hint="my_func")

    # Or use the engine directly
    engine = LLMTranspiler()
    if engine.available:
        rust = engine.transpile(python_code, name_hint="my_func")
"""

from __future__ import annotations

import os
import re
import subprocess  # nosec B404
import tempfile
import textwrap
from typing import Optional, Tuple

from Core.utils import logger

# ═══════════════════════════════════════════════════════════════════════════
#  System Prompt — tells the LLM exactly what we need
# ═══════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """\
You are a Python-to-Rust transpiler.  Your ONLY job is to convert
a Python function into an equivalent, idiomatic, **compilable** Rust function.

Rules:
• Output ONLY the Rust function — no explanations, no markdown fences.
• The function must be a standalone `fn` (no `impl` blocks, no traits).
• Use `std` only — no external crates.
• Use `String` for text, `Vec<T>` for lists, `HashMap<K,V>` for dicts.
• Add `use std::collections::{HashMap, HashSet};` ONLY if you use them.
• Preserve the original function name (snake_case).
• If the Python uses classes/self, extract the logic into a free function
  that takes the relevant fields as parameters.
• Prefer `.to_string()`, `.clone()`, `&str` parameter → `String` return.
• Do NOT use `unwrap()` on user data — use `unwrap_or`, `if let`, or match.
• Do NOT output `fn main()`.
• Do NOT include `#[test]`, `#[cfg(test)]`, or test modules.
• If you truly cannot translate the function, output exactly:
  `fn <name>() { todo!("cannot translate") }`
"""

_USER_TEMPLATE = """\
Convert this Python function to Rust:

```python
{python_code}
```

Output ONLY the Rust `fn` — no markdown, no explanation."""

# ═══════════════════════════════════════════════════════════════════════════
#  Rust Compiler Validation
# ═══════════════════════════════════════════════════════════════════════════

def _cleanup_temp_files(*paths: str):
    """Remove temp files, ignoring all errors."""
    for p in paths:
        try:
            if p:
                os.unlink(p)
        except Exception:  # nosec B110
            pass


def _check_rust_compiles(rust_code: str, *, timeout: int = 30) -> Tuple[bool, str]:
    """Validate *rust_code* by running ``rustc --edition 2021 --emit=metadata``.

    Uses ``--emit=metadata`` (type-checking only, no codegen) which is the
    ``rustc``-level equivalent of ``cargo check``.

    Returns ``(True, "")`` on success, or ``(False, error_text)`` on failure.
    """
    # Wrap in a minimal compilable unit
    wrapper = (
        "#![allow(unused_variables, unused_mut, dead_code, unused_imports)]\n"
        "#![allow(unreachable_code, unused_assignments)]\n"
        "use std::collections::{HashMap, HashSet};\n\n"
        f"{rust_code}\n\n"
        "fn main() {}\n"
    )
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".rs", mode="w", encoding="utf-8", delete=False
        ) as f:
            f.write(wrapper)
            tmp_path = f.name

        # --emit=metadata: type-check without producing a binary
        out_path = tmp_path.replace(".rs", ".rmeta")
        result = subprocess.run(  # nosec B603,B607
            ["rustc", "--edition", "2021", "--emit=metadata",
             "-o", out_path, tmp_path],
            capture_output=True, text=True, timeout=timeout,
        )
        ok = result.returncode == 0
        err = (result.stderr or "").strip()
        return ok, err
    except FileNotFoundError:
        return False, "rustc not found"
    except subprocess.TimeoutExpired:
        return False, "rustc timed out"
    except Exception as e:
        return False, str(e)
    finally:
        _cleanup_temp_files(tmp_path, tmp_path.replace(".rs", ".rmeta"))


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:])
    if text.endswith("```"):
        text = text[: text.rfind("```")]
    return text.strip()


def _match_braces(text: str, start: int) -> int:
    """Find the end of a brace-delimited block starting at *start*."""
    depth = 0
    in_fn = False
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
            in_fn = True
            continue
        if text[i] == "}":
            depth -= 1
            if depth == 0 and in_fn:
                return i + 1
    return len(text)


def _extract_fn_block(text: str) -> str:
    """Extract the first ``fn …{…}`` block from *text*.

    LLMs sometimes add explanations or markdown fences around the code.
    This pulls out just the function definition.
    """
    text = _strip_markdown_fences(text)

    # Find the first `fn ` and match braces
    fn_start = -1
    for m in re.finditer(r"(?:pub\s+)?fn\s+\w+", text):
        fn_start = m.start()
        break
    if fn_start < 0:
        return text  # return as-is; caller will validate

    # Collect any `use` lines that precede the fn
    prefix_lines = [
        line for line in text[:fn_start].split("\n")
        if line.strip().startswith("use ") or line.strip().startswith("//")
    ]

    fn_end = _match_braces(text, fn_start)
    fn_block = text[fn_start:fn_end].strip()
    if prefix_lines:
        return "\n".join(prefix_lines) + "\n" + fn_block
    return fn_block


# ═══════════════════════════════════════════════════════════════════════════
#  LLM Transpiler Engine
# ═══════════════════════════════════════════════════════════════════════════

class LLMTranspiler:
    """Transpile Python functions to Rust using a local LLM.

    Uses ``Core.inference.LLMHelper`` under the hood — talks to whatever
    llama.cpp / OpenAI-compatible server is configured in
    ``xray_settings.json`` or environment variables.
    """

    def __init__(self, *, max_retries: int = 2, verify_compilation: bool = True):
        self._max_retries = max_retries
        self._verify = verify_compilation
        self._llm: Optional[object] = None
        self._stats = {"attempted": 0, "success": 0, "compile_fail": 0, "llm_fail": 0}

    # ── Lazy init ─────────────────────────────────────────────────────

    def _get_llm(self):
        """Lazy-import and construct ``LLMHelper``."""
        if self._llm is None:
            try:
                from Core.inference import LLMHelper
                self._llm = LLMHelper()
            except Exception as e:
                logger.warning(f"LLMTranspiler: cannot init LLMHelper: {e}")
                self._llm = None
        return self._llm

    @property
    def available(self) -> bool:
        """True if the LLM server is reachable."""
        llm = self._get_llm()
        if llm is None:
            return False
        return llm.available

    @property
    def stats(self) -> dict:
        """Return transpilation statistics."""
        return dict(self._stats)

    def _query_llm(self, prompt: str) -> Optional[str]:
        """Send *prompt* to the LLM and return the raw response (or None)."""
        llm = self._get_llm()
        if llm is None or not llm.available:
            self._stats["llm_fail"] += 1
            return None
        try:
            raw = llm.completion(prompt, system_prompt=_SYSTEM_PROMPT)
        except Exception as e:
            logger.warning("LLMTranspiler: LLM query failed: %s", e)
            self._stats["llm_fail"] += 1
            return None
        if not raw or not raw.strip():
            self._stats["llm_fail"] += 1
            return None
        return raw

    def _finalize(self, rust_fn: str, source_info: str,
                  name_hint: str) -> str:
        """Prepend doc comment and record success."""
        tag = f"LLM-assisted transpilation from {source_info}" if source_info else "LLM-assisted transpilation"
        self._stats["success"] += 1
        logger.info("LLMTranspiler: ✓ %s transpiled via LLM", name_hint or "function")
        return f"/// {tag}\n{rust_fn}"

    # ── Core: transpile one function ──────────────────────────────────

    def transpile(self, python_code: str, *,
                  name_hint: str = "",
                  source_info: str = "",
                  error_context: str = "") -> Optional[str]:
        """Ask the LLM to transpile *python_code* to Rust.

        Returns valid Rust function code, or *None* on failure.
        """
        self._stats["attempted"] += 1
        user_msg = _USER_TEMPLATE.format(python_code=textwrap.dedent(python_code).strip())
        if error_context:
            user_msg += (
                "\n\nYour previous attempt failed to compile with these errors:\n"
                f"```\n{error_context}\n```\n"
                "Fix the errors and output ONLY the corrected Rust function."
            )

        raw = self._query_llm(user_msg)
        if raw is None:
            return None

        rust_fn = _extract_fn_block(raw)

        if self._verify:
            ok, errors = _check_rust_compiles(rust_fn)
            if not ok:
                self._stats["compile_fail"] += 1
                if self._max_retries > 0:
                    logger.info("LLMTranspiler: compile failed, retrying (%s)", name_hint)
                    return self._retry(python_code, rust_fn, errors,
                                       name_hint=name_hint,
                                       source_info=source_info,
                                       retries_left=self._max_retries - 1)
                return None

        return self._finalize(rust_fn, source_info, name_hint)

    def _retry(self, python_code: str, previous_rust: str, errors: str,
               *, name_hint: str, source_info: str,
               retries_left: int) -> Optional[str]:
        """Retry transpilation, feeding compiler errors back to the LLM."""
        if retries_left <= 0:
            return None

        repair_prompt = (
            f"Your previous Rust translation:\n```rust\n{previous_rust}\n```\n\n"
            f"Failed to compile with:\n```\n{errors}\n```\n\n"
            f"Original Python:\n```python\n{textwrap.dedent(python_code).strip()}\n```\n\n"
            "Fix the Rust code. Output ONLY the corrected Rust function."
        )

        raw = self._query_llm(repair_prompt)
        if raw is None:
            return None

        rust_fn = _extract_fn_block(raw)
        ok, new_errors = _check_rust_compiles(rust_fn)
        if ok:
            return self._finalize(rust_fn, source_info, name_hint)
        self._stats["compile_fail"] += 1
        return self._retry(python_code, rust_fn, new_errors,
                           name_hint=name_hint,
                           source_info=source_info,
                           retries_left=retries_left - 1) if retries_left > 1 else None


# ═══════════════════════════════════════════════════════════════════════════
#  Singleton & Convenience API
# ═══════════════════════════════════════════════════════════════════════════

_default_engine: Optional[LLMTranspiler] = None


def get_llm_transpiler() -> LLMTranspiler:
    """Return (or create) the default ``LLMTranspiler`` singleton."""
    global _default_engine
    if _default_engine is None:
        _default_engine = LLMTranspiler()
    return _default_engine


def get_cached_llm_transpiler() -> Optional[LLMTranspiler]:
    """Return a cached LLM transpiler if available, else *None*.

    Uses a function-attribute cache so the availability check and
    ``get_llm_transpiler()`` call happen at most once per process.
    """
    if not hasattr(get_cached_llm_transpiler, "_cache"):
        try:
            eng = get_llm_transpiler()
            get_cached_llm_transpiler._cache = eng if eng.available else None
        except Exception:
            get_cached_llm_transpiler._cache = None
    return get_cached_llm_transpiler._cache


def llm_transpile_function(python_code: str, *,
                           name_hint: str = "",
                           source_info: str = "") -> Optional[str]:
    """Convenience wrapper: transpile one function via the default engine.

    Returns the Rust code or *None* if the LLM is unavailable / fails.
    """
    engine = get_llm_transpiler()
    return engine.transpile(python_code, name_hint=name_hint,
                            source_info=source_info)


def hybrid_transpile(python_code: str, *,
                     name_hint: str = "",
                     source_info: str = "") -> str:
    """Hybrid transpilation: AST first, LLM fallback.

    1. Tries the fast, deterministic AST transpiler.
    2. If the result contains ``todo!()``, falls back to the LLM.
    3. If the LLM also fails, returns the original ``todo!()`` stub.

    Always returns valid, compilable Rust.
    """
    from Analysis.transpiler import transpile_function_code
    from Analysis.transpiler_legacy import _sanitize_generated

    # Step 1: AST transpiler (fast)
    ast_result = transpile_function_code(
        python_code, name_hint=name_hint, source_info=source_info
    )
    ast_result = _sanitize_generated(ast_result)

    # If AST produced real Rust (no todo!), we're done
    if "todo!" not in ast_result:
        return ast_result

    # Step 2: LLM fallback
    engine = get_llm_transpiler()
    if not engine.available:
        return ast_result  # no LLM — keep the todo!() stub

    llm_result = engine.transpile(
        python_code, name_hint=name_hint, source_info=source_info
    )

    if llm_result is not None:
        return llm_result

    # LLM failed — return the safe AST stub
    return ast_result
