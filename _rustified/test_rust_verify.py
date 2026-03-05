"""Auto-generated: verify Rust DLL outputs match Python goldens."""
import json, pathlib, pytest

try:
    import xray_rustified
    HAS_RUST = True
except ImportError:
    HAS_RUST = False

FIXTURE_DIR = pathlib.Path(r"C:\Users\dvdze\Documents\_Python\X_Ray\_rustified\golden")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust_score_pair_detailed():
    """Verify Rust score_pair_detailed matches Python golden."""
    golden_path = FIXTURE_DIR / "score_pair_detailed_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "score_pair_detailed", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust_semantic_similarity():
    """Verify Rust semantic_similarity matches Python golden."""
    golden_path = FIXTURE_DIR / "semantic_similarity_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "semantic_similarity", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust__classify_token():
    """Verify Rust _classify_token matches Python golden."""
    golden_path = FIXTURE_DIR / "_classify_token_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_classify_token", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust__classify_name():
    """Verify Rust _classify_name matches Python golden."""
    golden_path = FIXTURE_DIR / "_classify_name_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_classify_name", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust_assert_tokenize_snake_case():
    """Verify Rust assert_tokenize_snake_case matches Python golden."""
    golden_path = FIXTURE_DIR / "assert_tokenize_snake_case_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "assert_tokenize_snake_case", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust_assert_tokenize_camel_case():
    """Verify Rust assert_tokenize_camel_case matches Python golden."""
    golden_path = FIXTURE_DIR / "assert_tokenize_camel_case_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "assert_tokenize_camel_case", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust__strip_markdown_fences():
    """Verify Rust _strip_markdown_fences matches Python golden."""
    golden_path = FIXTURE_DIR / "_strip_markdown_fences_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_strip_markdown_fences", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust__token_ngram_similarity():
    """Verify Rust _token_ngram_similarity matches Python golden."""
    golden_path = FIXTURE_DIR / "_token_ngram_similarity_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_token_ngram_similarity", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust_name_similarity():
    """Verify Rust name_similarity matches Python golden."""
    golden_path = FIXTURE_DIR / "name_similarity_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "name_similarity", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust_callgraph_overlap():
    """Verify Rust callgraph_overlap matches Python golden."""
    golden_path = FIXTURE_DIR / "callgraph_overlap_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "callgraph_overlap", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust__safe_repr():
    """Verify Rust _safe_repr matches Python golden."""
    golden_path = FIXTURE_DIR / "_safe_repr_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_safe_repr", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust__make_func():
    """Verify Rust _make_func matches Python golden."""
    golden_path = FIXTURE_DIR / "_make_func_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_make_func", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust__delta_int():
    """Verify Rust _delta_int matches Python golden."""
    golden_path = FIXTURE_DIR / "_delta_int_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_delta_int", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust__delta_float():
    """Verify Rust _delta_float matches Python golden."""
    golden_path = FIXTURE_DIR / "_delta_float_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_delta_float", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust__detect_gpu():
    """Verify Rust _detect_gpu matches Python golden."""
    golden_path = FIXTURE_DIR / "_detect_gpu_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_detect_gpu", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust__boom():
    """Verify Rust _boom matches Python golden."""
    golden_path = FIXTURE_DIR / "_boom_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_boom", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust_cached_factorial():
    """Verify Rust cached_factorial matches Python golden."""
    golden_path = FIXTURE_DIR / "cached_factorial_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "cached_factorial", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust__make_class():
    """Verify Rust _make_class matches Python golden."""
    golden_path = FIXTURE_DIR / "_make_class_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_make_class", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust__make_smell():
    """Verify Rust _make_smell matches Python golden."""
    golden_path = FIXTURE_DIR / "_make_smell_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_make_smell", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust_llm_transpile_function():
    """Verify Rust llm_transpile_function matches Python golden."""
    golden_path = FIXTURE_DIR / "llm_transpile_function_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "llm_transpile_function", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust_run_smell_phase():
    """Verify Rust run_smell_phase matches Python golden."""
    golden_path = FIXTURE_DIR / "run_smell_phase_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "run_smell_phase", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust_run_duplicate_phase():
    """Verify Rust run_duplicate_phase matches Python golden."""
    golden_path = FIXTURE_DIR / "run_duplicate_phase_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "run_duplicate_phase", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust__ast_histogram_similarity():
    """Verify Rust _ast_histogram_similarity matches Python golden."""
    golden_path = FIXTURE_DIR / "_ast_histogram_similarity_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_ast_histogram_similarity", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust_tmp_py_file():
    """Verify Rust tmp_py_file matches Python golden."""
    golden_path = FIXTURE_DIR / "tmp_py_file_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "tmp_py_file", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust__query_llm():
    """Verify Rust _query_llm matches Python golden."""
    golden_path = FIXTURE_DIR / "_query_llm_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_query_llm", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust__retry():
    """Verify Rust _retry matches Python golden."""
    golden_path = FIXTURE_DIR / "_retry_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_retry", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust_generate_llm_vectors():
    """Verify Rust generate_llm_vectors matches Python golden."""
    golden_path = FIXTURE_DIR / "generate_llm_vectors_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "generate_llm_vectors", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust_fix_all():
    """Verify Rust fix_all matches Python golden."""
    golden_path = FIXTURE_DIR / "fix_all_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "fix_all", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust_get_cached_llm_transpiler():
    """Verify Rust get_cached_llm_transpiler matches Python golden."""
    golden_path = FIXTURE_DIR / "get_cached_llm_transpiler_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "get_cached_llm_transpiler", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust___init__():
    """Verify Rust __init__ matches Python golden."""
    golden_path = FIXTURE_DIR / "__init___golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "__init__", None)
    if rust_fn is None:
        pytest.skip("function not in Rust module")
    for case in goldens:
        if case.get('error'):
            continue  # skip error cases
        kwargs = case['input']
        expected = case['output']
        try:
            result = repr(rust_fn(**kwargs))
        except Exception as e:
            pytest.fail(f"Rust raised {e} for input {kwargs}")
        assert result == expected, (
            f"Mismatch: Rust={result} vs Python={expected} for input={kwargs}")
