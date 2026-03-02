"""Auto-generated: verify Rust DLL outputs match Python goldens."""
import json, pathlib, pytest

try:
    import x_ray_rustified
    HAS_RUST = True
except ImportError:
    HAS_RUST = False

FIXTURE_DIR = pathlib.Path(r"C:\Users\Yo930\Desktop\_Python\X_Ray\_rustified_exe_build\golden")

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_collect_reports():
    """Verify Rust collect_reports matches Python golden."""
    golden_path = FIXTURE_DIR / "collect_reports_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "collect_reports", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__extract_fn_block():
    """Verify Rust _extract_fn_block matches Python golden."""
    golden_path = FIXTURE_DIR / "_extract_fn_block_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_extract_fn_block", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_cosine_similarity():
    """Verify Rust cosine_similarity matches Python golden."""
    golden_path = FIXTURE_DIR / "cosine_similarity_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "cosine_similarity", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__get_accepted_params():
    """Verify Rust _get_accepted_params matches Python golden."""
    golden_path = FIXTURE_DIR / "_get_accepted_params_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_get_accepted_params", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__match_braces():
    """Verify Rust _match_braces matches Python golden."""
    golden_path = FIXTURE_DIR / "_match_braces_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_match_braces", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_update_setting():
    """Verify Rust update_setting matches Python golden."""
    golden_path = FIXTURE_DIR / "update_setting_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "update_setting", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_code_similarity():
    """Verify Rust code_similarity matches Python golden."""
    golden_path = FIXTURE_DIR / "code_similarity_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "code_similarity", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__should_prune_dir():
    """Verify Rust _should_prune_dir matches Python golden."""
    golden_path = FIXTURE_DIR / "_should_prune_dir_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_should_prune_dir", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_get_setting():
    """Verify Rust get_setting matches Python golden."""
    golden_path = FIXTURE_DIR / "get_setting_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "get_setting", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_semantic_similarity():
    """Verify Rust semantic_similarity matches Python golden."""
    golden_path = FIXTURE_DIR / "semantic_similarity_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "semantic_similarity", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__detect_gpu_nvidia():
    """Verify Rust _detect_gpu_nvidia matches Python golden."""
    golden_path = FIXTURE_DIR / "_detect_gpu_nvidia_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_detect_gpu_nvidia", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__build_smell_summary():
    """Verify Rust _build_smell_summary matches Python golden."""
    golden_path = FIXTURE_DIR / "_build_smell_summary_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_build_smell_summary", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_score_pair_detailed():
    """Verify Rust score_pair_detailed matches Python golden."""
    golden_path = FIXTURE_DIR / "score_pair_detailed_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "score_pair_detailed", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__detect_gpu_amd():
    """Verify Rust _detect_gpu_amd matches Python golden."""
    golden_path = FIXTURE_DIR / "_detect_gpu_amd_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_detect_gpu_amd", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_build_json_report():
    """Verify Rust build_json_report matches Python golden."""
    golden_path = FIXTURE_DIR / "build_json_report_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "build_json_report", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__deep_merge():
    """Verify Rust _deep_merge matches Python golden."""
    golden_path = FIXTURE_DIR / "_deep_merge_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_deep_merge", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__enable_utf8_console():
    """Verify Rust _enable_utf8_console matches Python golden."""
    golden_path = FIXTURE_DIR / "_enable_utf8_console_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_enable_utf8_console", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__find_owning_function():
    """Verify Rust _find_owning_function matches Python golden."""
    golden_path = FIXTURE_DIR / "_find_owning_function_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_find_owning_function", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__count_functions_in_files():
    """Verify Rust _count_functions_in_files matches Python golden."""
    golden_path = FIXTURE_DIR / "_count_functions_in_files_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_count_functions_in_files", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__classify_token():
    """Verify Rust _classify_token matches Python golden."""
    golden_path = FIXTURE_DIR / "_classify_token_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_classify_token", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_sanitize_fn_name():
    """Verify Rust sanitize_fn_name matches Python golden."""
    golden_path = FIXTURE_DIR / "sanitize_fn_name_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "sanitize_fn_name", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__matches_include_filter():
    """Verify Rust _matches_include_filter matches Python golden."""
    golden_path = FIXTURE_DIR / "_matches_include_filter_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_matches_include_filter", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__count_external_deps():
    """Verify Rust _count_external_deps matches Python golden."""
    golden_path = FIXTURE_DIR / "_count_external_deps_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_count_external_deps", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__classify_name():
    """Verify Rust _classify_name matches Python golden."""
    golden_path = FIXTURE_DIR / "_classify_name_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_classify_name", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_mock_transpile_to_rust_v2():
    """Verify Rust mock_transpile_to_rust_v2 matches Python golden."""
    golden_path = FIXTURE_DIR / "mock_transpile_to_rust_v2_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "mock_transpile_to_rust_v2", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__suggest_module_name_py():
    """Verify Rust _suggest_module_name_py matches Python golden."""
    golden_path = FIXTURE_DIR / "_suggest_module_name_py_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_suggest_module_name_py", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_assert_tokenize_snake_case():
    """Verify Rust assert_tokenize_snake_case matches Python golden."""
    golden_path = FIXTURE_DIR / "assert_tokenize_snake_case_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "assert_tokenize_snake_case", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_assert_tokenize_camel_case():
    """Verify Rust assert_tokenize_camel_case matches Python golden."""
    golden_path = FIXTURE_DIR / "assert_tokenize_camel_case_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "assert_tokenize_camel_case", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__build_dup_summary():
    """Verify Rust _build_dup_summary matches Python golden."""
    golden_path = FIXTURE_DIR / "_build_dup_summary_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_build_dup_summary", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__strip_markdown_fences():
    """Verify Rust _strip_markdown_fences matches Python golden."""
    golden_path = FIXTURE_DIR / "_strip_markdown_fences_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_strip_markdown_fences", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__enable_windows_utf8():
    """Verify Rust _enable_windows_utf8 matches Python golden."""
    golden_path = FIXTURE_DIR / "_enable_windows_utf8_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_enable_windows_utf8", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__token_ngram_similarity():
    """Verify Rust _token_ngram_similarity matches Python golden."""
    golden_path = FIXTURE_DIR / "_token_ngram_similarity_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_token_ngram_similarity", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_name_similarity():
    """Verify Rust name_similarity matches Python golden."""
    golden_path = FIXTURE_DIR / "name_similarity_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "name_similarity", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_callgraph_overlap():
    """Verify Rust callgraph_overlap matches Python golden."""
    golden_path = FIXTURE_DIR / "callgraph_overlap_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "callgraph_overlap", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__safe_repr():
    """Verify Rust _safe_repr matches Python golden."""
    golden_path = FIXTURE_DIR / "_safe_repr_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_safe_repr", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__score_to_letter():
    """Verify Rust _score_to_letter matches Python golden."""
    golden_path = FIXTURE_DIR / "_score_to_letter_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_score_to_letter", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__top_params():
    """Verify Rust _top_params matches Python golden."""
    golden_path = FIXTURE_DIR / "_top_params_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_top_params", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_classify_margin_py():
    """Verify Rust classify_margin_py matches Python golden."""
    golden_path = FIXTURE_DIR / "classify_margin_py_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "classify_margin_py", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_classify_margin():
    """Verify Rust classify_margin matches Python golden."""
    golden_path = FIXTURE_DIR / "classify_margin_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "classify_margin", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__build_lib_summary():
    """Verify Rust _build_lib_summary matches Python golden."""
    golden_path = FIXTURE_DIR / "_build_lib_summary_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_build_lib_summary", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__detect_gpu():
    """Verify Rust _detect_gpu matches Python golden."""
    golden_path = FIXTURE_DIR / "_detect_gpu_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_detect_gpu", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__wrap_stream_utf8():
    """Verify Rust _wrap_stream_utf8 matches Python golden."""
    golden_path = FIXTURE_DIR / "_wrap_stream_utf8_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_wrap_stream_utf8", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__cpu_brand_darwin():
    """Verify Rust _cpu_brand_darwin matches Python golden."""
    golden_path = FIXTURE_DIR / "_cpu_brand_darwin_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_cpu_brand_darwin", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__type_tag():
    """Verify Rust _type_tag matches Python golden."""
    golden_path = FIXTURE_DIR / "_type_tag_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_type_tag", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_add_common_scan_args():
    """Verify Rust add_common_scan_args matches Python golden."""
    golden_path = FIXTURE_DIR / "add_common_scan_args_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "add_common_scan_args", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_outer_function():
    """Verify Rust outer_function matches Python golden."""
    golden_path = FIXTURE_DIR / "outer_function_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "outer_function", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_star_args_func():
    """Verify Rust star_args_func matches Python golden."""
    golden_path = FIXTURE_DIR / "star_args_func_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "star_args_func", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_get_cpu_info():
    """Verify Rust get_cpu_info matches Python golden."""
    golden_path = FIXTURE_DIR / "get_cpu_info_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "get_cpu_info", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__boom():
    """Verify Rust _boom matches Python golden."""
    golden_path = FIXTURE_DIR / "_boom_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_boom", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_cached_factorial():
    """Verify Rust cached_factorial matches Python golden."""
    golden_path = FIXTURE_DIR / "cached_factorial_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "cached_factorial", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_compile_rust():
    """Verify Rust compile_rust matches Python golden."""
    golden_path = FIXTURE_DIR / "compile_rust_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "compile_rust", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_run_cargo_check():
    """Verify Rust run_cargo_check matches Python golden."""
    golden_path = FIXTURE_DIR / "run_cargo_check_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "run_cargo_check", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_llm_transpile_function():
    """Verify Rust llm_transpile_function matches Python golden."""
    golden_path = FIXTURE_DIR / "llm_transpile_function_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "llm_transpile_function", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_scan_codebase():
    """Verify Rust scan_codebase matches Python golden."""
    golden_path = FIXTURE_DIR / "scan_codebase_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "scan_codebase", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__cpu_brand_windows():
    """Verify Rust _cpu_brand_windows matches Python golden."""
    golden_path = FIXTURE_DIR / "_cpu_brand_windows_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_cpu_brand_windows", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__avail_ram_gb_darwin():
    """Verify Rust _avail_ram_gb_darwin matches Python golden."""
    golden_path = FIXTURE_DIR / "_avail_ram_gb_darwin_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_avail_ram_gb_darwin", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_setup_logger():
    """Verify Rust setup_logger matches Python golden."""
    golden_path = FIXTURE_DIR / "setup_logger_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "setup_logger", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__ram_gb_darwin():
    """Verify Rust _ram_gb_darwin matches Python golden."""
    golden_path = FIXTURE_DIR / "_ram_gb_darwin_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_ram_gb_darwin", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__ast_histogram_similarity():
    """Verify Rust _ast_histogram_similarity matches Python golden."""
    golden_path = FIXTURE_DIR / "_ast_histogram_similarity_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_ast_histogram_similarity", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__make_node():
    """Verify Rust _make_node matches Python golden."""
    golden_path = FIXTURE_DIR / "_make_node_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_make_node", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_to_dict():
    """Verify Rust to_dict matches Python golden."""
    golden_path = FIXTURE_DIR / "to_dict_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "to_dict", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__validate_call():
    """Verify Rust _validate_call matches Python golden."""
    golden_path = FIXTURE_DIR / "_validate_call_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_validate_call", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_recommended_gpu_layers():
    """Verify Rust recommended_gpu_layers matches Python golden."""
    golden_path = FIXTURE_DIR / "recommended_gpu_layers_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "recommended_gpu_layers", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__query_llm():
    """Verify Rust _query_llm matches Python golden."""
    golden_path = FIXTURE_DIR / "_query_llm_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_query_llm", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_tier():
    """Verify Rust tier matches Python golden."""
    golden_path = FIXTURE_DIR / "tier_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "tier", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__auto_suggest():
    """Verify Rust _auto_suggest matches Python golden."""
    golden_path = FIXTURE_DIR / "_auto_suggest_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_auto_suggest", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__compare_executions():
    """Verify Rust _compare_executions matches Python golden."""
    golden_path = FIXTURE_DIR / "_compare_executions_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_compare_executions", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_generate_llm_vectors():
    """Verify Rust generate_llm_vectors matches Python golden."""
    golden_path = FIXTURE_DIR / "generate_llm_vectors_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "generate_llm_vectors", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__retry():
    """Verify Rust _retry matches Python golden."""
    golden_path = FIXTURE_DIR / "_retry_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_retry", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_write_html():
    """Verify Rust write_html matches Python golden."""
    golden_path = FIXTURE_DIR / "write_html_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "write_html", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__is_cross_file_candidate():
    """Verify Rust _is_cross_file_candidate matches Python golden."""
    golden_path = FIXTURE_DIR / "_is_cross_file_candidate_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_is_cross_file_candidate", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_get_cached_llm_transpiler():
    """Verify Rust get_cached_llm_transpiler matches Python golden."""
    golden_path = FIXTURE_DIR / "get_cached_llm_transpiler_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "get_cached_llm_transpiler", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__get_llm():
    """Verify Rust _get_llm matches Python golden."""
    golden_path = FIXTURE_DIR / "_get_llm_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_get_llm", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__suggest_module_name():
    """Verify Rust _suggest_module_name matches Python golden."""
    golden_path = FIXTURE_DIR / "_suggest_module_name_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_suggest_module_name", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_profile_for():
    """Verify Rust profile_for matches Python golden."""
    golden_path = FIXTURE_DIR / "profile_for_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "profile_for", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust__to_smell_issue():
    """Verify Rust _to_smell_issue matches Python golden."""
    golden_path = FIXTURE_DIR / "_to_smell_issue_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "_to_smell_issue", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_detect():
    """Verify Rust detect matches Python golden."""
    golden_path = FIXTURE_DIR / "detect_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "detect", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust___init__():
    """Verify Rust __init__ matches Python golden."""
    golden_path = FIXTURE_DIR / "__init___golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "__init__", None)
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

@pytest.mark.skipif(not HAS_RUST, reason="x_ray_rustified not compiled")
def test_rust_collect_py_files():
    """Verify Rust collect_py_files matches Python golden."""
    golden_path = FIXTURE_DIR / "collect_py_files_golden.json"
    if not golden_path.exists():
        pytest.skip("golden fixture not found")
    goldens = json.loads(golden_path.read_text())
    rust_fn = getattr(x_ray_rustified, "collect_py_files", None)
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
