"""Auto-generated: verify Rust DLL outputs match Python goldens."""
import json, pathlib, pytest

try:
    import xray_rustified
    HAS_RUST = True
except ImportError:
    HAS_RUST = False

FIXTURE_DIR = pathlib.Path(r"C:\Users\dvdze\Documents\_Python\X_Ray\_rustified\golden")

@pytest.mark.skipif(not HAS_RUST, reason="xray_rustified not compiled")
def test_rust_metric_tile():
    """Verify Rust metric_tile matches Python golden."""
    golden_path = FIXTURE_DIR / "metric_tile_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "metric_tile", None)
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
def test_rust_section_title():
    """Verify Rust section_title matches Python golden."""
    golden_path = FIXTURE_DIR / "section_title_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "section_title", None)
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
def test_rust__has_return_annotation():
    """Verify Rust _has_return_annotation matches Python golden."""
    golden_path = FIXTURE_DIR / "_has_return_annotation_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_has_return_annotation", None)
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
def test_rust__grade_ge():
    """Verify Rust _grade_ge matches Python golden."""
    golden_path = FIXTURE_DIR / "_grade_ge_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_grade_ge", None)
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
def test_rust__make_proportional_bar():
    """Verify Rust _make_proportional_bar matches Python golden."""
    golden_path = FIXTURE_DIR / "_make_proportional_bar_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_make_proportional_bar", None)
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
def test_rust__code_panel():
    """Verify Rust _code_panel matches Python golden."""
    golden_path = FIXTURE_DIR / "_code_panel_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_code_panel", None)
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
def test_rust__code_snippet_container():
    """Verify Rust _code_snippet_container matches Python golden."""
    golden_path = FIXTURE_DIR / "_code_snippet_container_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_code_snippet_container", None)
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
def test_rust__build_cargo_error_log():
    """Verify Rust _build_cargo_error_log matches Python golden."""
    golden_path = FIXTURE_DIR / "_build_cargo_error_log_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_build_cargo_error_log", None)
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
def test_rust_get_cache():
    """Verify Rust get_cache matches Python golden."""
    golden_path = FIXTURE_DIR / "get_cache_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "get_cache", None)
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
def test_rust__empty_state():
    """Verify Rust _empty_state matches Python golden."""
    golden_path = FIXTURE_DIR / "_empty_state_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_empty_state", None)
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
def test_rust_get_llm_transpiler():
    """Verify Rust get_llm_transpiler matches Python golden."""
    golden_path = FIXTURE_DIR / "get_llm_transpiler_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "get_llm_transpiler", None)
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
def test_rust__empty_result_box():
    """Verify Rust _empty_result_box matches Python golden."""
    golden_path = FIXTURE_DIR / "_empty_result_box_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(xray_rustified, "_empty_result_box", None)
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
