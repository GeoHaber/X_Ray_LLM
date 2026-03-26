"""
LLM Mock Tests — verify generate_test, generate_fix, analyze_codebase
work correctly with mocked model responses.

Run:  python -m pytest tests/test_llm_mock.py -v --tb=short
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from xray.llm import GGML_KV_TYPES, LLMConfig, LLMEngine, _resolve_kv_type


def _make_engine_with_mock():
    """Create an LLMEngine with a mocked model that returns predictable responses."""
    config = LLMConfig(model_path="/fake/model.gguf")
    engine = LLMEngine(config=config)

    # Mock the model
    mock_model = MagicMock()
    mock_model.create_chat_completion.return_value = {"choices": [{"message": {"content": "MOCK_RESPONSE"}}]}
    engine._model = mock_model
    return engine, mock_model


# ═════════════════════════════════════════════════════════════════════════════
# 1. generate() basics
# ═════════════════════════════════════════════════════════════════════════════


class TestGenerate:
    """Test the raw generate() method with mocked model."""

    def test_generate_returns_string(self):
        engine, _mock = _make_engine_with_mock()
        result = engine.generate("Hello")
        assert result == "MOCK_RESPONSE"

    def test_generate_passes_user_message(self):
        engine, mock = _make_engine_with_mock()
        engine.generate("test prompt")
        call_args = mock.create_chat_completion.call_args
        messages = call_args[1]["messages"] if "messages" in call_args[1] else call_args[0][0]
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "test prompt"

    def test_generate_with_system_prompt(self):
        engine, mock = _make_engine_with_mock()
        engine.generate("prompt", system="You are helpful")
        call_args = mock.create_chat_completion.call_args
        messages = call_args[1].get("messages", call_args[0][0] if call_args[0] else [])
        system_msgs = [m for m in messages if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0]["content"] == "You are helpful"

    def test_generate_without_system_prompt(self):
        engine, mock = _make_engine_with_mock()
        engine.generate("prompt")
        call_args = mock.create_chat_completion.call_args
        messages = call_args[1].get("messages", call_args[0][0] if call_args[0] else [])
        system_msgs = [m for m in messages if m["role"] == "system"]
        assert len(system_msgs) == 0

    def test_generate_uses_config_temperature(self):
        config = LLMConfig(model_path="/fake.gguf", temperature=0.7)
        engine = LLMEngine(config=config)
        mock = MagicMock()
        mock.create_chat_completion.return_value = {"choices": [{"message": {"content": "ok"}}]}
        engine._model = mock

        engine.generate("test")
        call_args = mock.create_chat_completion.call_args
        assert call_args[1]["temperature"] == 0.7

    def test_generate_max_tokens_override(self):
        engine, mock = _make_engine_with_mock()
        engine.generate("test", max_tokens=512)
        call_args = mock.create_chat_completion.call_args
        assert call_args[1]["max_tokens"] == 512


# ═════════════════════════════════════════════════════════════════════════════
# 2. generate_test()
# ═════════════════════════════════════════════════════════════════════════════


class TestGenerateTest:
    """Test the generate_test() method."""

    def test_returns_string(self):
        engine, _mock = _make_engine_with_mock()
        finding = {
            "rule_id": "SEC-007",
            "severity": "HIGH",
            "description": "eval() usage",
            "file": "test.py",
            "line": 5,
            "test_hint": "Test that eval is not used",
        }
        result = engine.generate_test(finding, "source context here")
        assert isinstance(result, str)

    def test_includes_rule_info_in_prompt(self):
        engine, mock = _make_engine_with_mock()
        finding = {
            "rule_id": "SEC-003",
            "severity": "HIGH",
            "description": "shell=True",
            "file": "app.py",
            "line": 10,
            "test_hint": "Verify shell=False",
        }
        engine.generate_test(finding, "context")
        call_args = mock.create_chat_completion.call_args
        messages = call_args[1].get("messages", [])
        user_msg = next(m for m in messages if m["role"] == "user")["content"]
        assert "SEC-003" in user_msg
        assert "shell=True" in user_msg

    def test_system_prompt_mentions_pytest(self):
        engine, mock = _make_engine_with_mock()
        finding = {"rule_id": "X", "severity": "LOW", "description": "x", "file": "x.py", "line": 1, "test_hint": "x"}
        engine.generate_test(finding, "ctx")
        call_args = mock.create_chat_completion.call_args
        messages = call_args[1].get("messages", [])
        system_msg = next(m for m in messages if m["role"] == "system")["content"]
        assert "pytest" in system_msg


# ═════════════════════════════════════════════════════════════════════════════
# 3. generate_fix()
# ═════════════════════════════════════════════════════════════════════════════


class TestGenerateFix:
    """Test the generate_fix() method."""

    def test_returns_string(self):
        engine, _mock = _make_engine_with_mock()
        finding = {
            "rule_id": "QUAL-001",
            "severity": "MEDIUM",
            "description": "bare except",
            "fix_hint": "Use except Exception:",
            "file": "app.py",
            "line": 3,
        }
        result = engine.generate_fix(finding, "source context")
        assert isinstance(result, str)

    def test_includes_fix_hint_in_prompt(self):
        engine, mock = _make_engine_with_mock()
        finding = {
            "rule_id": "PY-007",
            "severity": "MEDIUM",
            "description": "os.environ[]",
            "fix_hint": "Use .get() with default",
            "file": "x.py",
            "line": 1,
        }
        engine.generate_fix(finding, "ctx")
        call_args = mock.create_chat_completion.call_args
        messages = call_args[1].get("messages", [])
        user_msg = next(m for m in messages if m["role"] == "user")["content"]
        assert "Use .get() with default" in user_msg

    def test_includes_test_error_when_provided(self):
        engine, mock = _make_engine_with_mock()
        finding = {"rule_id": "X", "severity": "LOW", "description": "x", "fix_hint": "fix", "file": "x.py", "line": 1}
        engine.generate_fix(finding, "ctx", test_error="AssertionError: x != y")
        call_args = mock.create_chat_completion.call_args
        messages = call_args[1].get("messages", [])
        user_msg = next(m for m in messages if m["role"] == "user")["content"]
        assert "AssertionError" in user_msg

    def test_no_test_error_omits_section(self):
        engine, mock = _make_engine_with_mock()
        finding = {"rule_id": "X", "severity": "LOW", "description": "x", "fix_hint": "fix", "file": "x.py", "line": 1}
        engine.generate_fix(finding, "ctx", test_error="")
        call_args = mock.create_chat_completion.call_args
        messages = call_args[1].get("messages", [])
        user_msg = next(m for m in messages if m["role"] == "user")["content"]
        assert "previous fix attempt" not in user_msg


# ═════════════════════════════════════════════════════════════════════════════
# 4. analyze_codebase()
# ═════════════════════════════════════════════════════════════════════════════


class TestAnalyzeCodebase:
    """Test the analyze_codebase() method."""

    def test_returns_string(self):
        engine, _mock = _make_engine_with_mock()
        result = engine.analyze_codebase("5 HIGH, 3 MEDIUM findings")
        assert isinstance(result, str)

    def test_system_prompt_mentions_auditor(self):
        engine, mock = _make_engine_with_mock()
        engine.analyze_codebase("summary")
        call_args = mock.create_chat_completion.call_args
        messages = call_args[1].get("messages", [])
        system_msg = next(m for m in messages if m["role"] == "system")["content"]
        assert "auditor" in system_msg.lower()


# ═════════════════════════════════════════════════════════════════════════════
# 5. _ensure_model thread safety
# ═════════════════════════════════════════════════════════════════════════════


class TestEnsureModel:
    """Test model loading edge cases."""

    def test_ensure_model_raises_without_path(self):
        engine = LLMEngine(config=LLMConfig(model_path=""))
        with pytest.raises(RuntimeError, match="No model path"):
            engine._ensure_model()

    def test_ensure_model_skips_if_loaded(self):
        engine = LLMEngine(config=LLMConfig(model_path=""))
        engine._model = "already loaded"
        # Should return immediately without raising
        engine._ensure_model()

    def test_unload_clears_model(self):
        engine, _ = _make_engine_with_mock()
        assert engine._model is not None
        engine.unload()
        assert engine._model is None

    def test_is_available_false_for_empty_path(self):
        engine = LLMEngine(config=LLMConfig(model_path=""))
        assert not engine.is_available

    def test_is_available_false_for_nonexistent(self):
        engine = LLMEngine(config=LLMConfig(model_path="/no/such/model.gguf"))
        assert not engine.is_available


# ═════════════════════════════════════════════════════════════════════════════
# 6. TurboQuant KV cache quantization config
# ═════════════════════════════════════════════════════════════════════════════


class TestKVCacheQuantization:
    """Test TurboQuant / KV cache quantization configuration."""

    # -- _resolve_kv_type --

    def test_resolve_empty_string_returns_none(self):
        assert _resolve_kv_type("") is None

    def test_resolve_raw_integer_string(self):
        assert _resolve_kv_type("8") == 8

    def test_resolve_named_type_q8_0(self):
        assert _resolve_kv_type("q8_0") == 8

    def test_resolve_named_type_q4_0(self):
        assert _resolve_kv_type("q4_0") == 2

    def test_resolve_named_type_f16(self):
        assert _resolve_kv_type("f16") == 1

    def test_resolve_case_insensitive(self):
        assert _resolve_kv_type("Q8_0") == 8
        assert _resolve_kv_type("F16") == 1

    def test_resolve_with_whitespace(self):
        assert _resolve_kv_type("  q4_0  ") == 2

    def test_resolve_unknown_name_raises(self):
        with pytest.raises(ValueError, match="Unknown KV cache type"):
            _resolve_kv_type("turbo99")

    # -- GGML_KV_TYPES dict --

    def test_ggml_kv_types_has_expected_entries(self):
        assert "f16" in GGML_KV_TYPES
        assert "q8_0" in GGML_KV_TYPES
        assert "q4_0" in GGML_KV_TYPES

    # -- LLMConfig defaults --

    def test_config_defaults_none(self):
        cfg = LLMConfig()
        assert cfg.type_k is None
        assert cfg.type_v is None
        assert cfg.flash_attn is False

    def test_config_explicit_values(self):
        cfg = LLMConfig(type_k=8, type_v=2, flash_attn=True)
        assert cfg.type_k == 8
        assert cfg.type_v == 2
        assert cfg.flash_attn is True

    # -- from_env --

    def test_from_env_type_k_name(self, monkeypatch):
        monkeypatch.setenv("XRAY_TYPE_K", "q8_0")
        cfg = LLMConfig.from_env()
        assert cfg.type_k == 8

    def test_from_env_type_v_raw_int(self, monkeypatch):
        monkeypatch.setenv("XRAY_TYPE_V", "2")
        cfg = LLMConfig.from_env()
        assert cfg.type_v == 2

    def test_from_env_flash_attn_true(self, monkeypatch):
        monkeypatch.setenv("XRAY_FLASH_ATTN", "1")
        cfg = LLMConfig.from_env()
        assert cfg.flash_attn is True

    def test_from_env_flash_attn_yes(self, monkeypatch):
        monkeypatch.setenv("XRAY_FLASH_ATTN", "yes")
        cfg = LLMConfig.from_env()
        assert cfg.flash_attn is True

    def test_from_env_flash_attn_default_false(self):
        cfg = LLMConfig.from_env()
        assert cfg.flash_attn is False

    def test_from_env_no_kv_types_set(self):
        cfg = LLMConfig.from_env()
        assert cfg.type_k is None
        assert cfg.type_v is None

    # -- _ensure_model kwargs propagation --

    def test_ensure_model_passes_type_k_and_v(self, monkeypatch):
        """Verify type_k/type_v are forwarded to the Llama constructor."""
        captured_kwargs = {}

        class FakeLlama:
            def __init__(self, **kw):
                captured_kwargs.update(kw)

        monkeypatch.setattr("xray.llm.Llama", FakeLlama, raising=False)
        # Need to patch the import path used inside _ensure_model
        import xray.llm as llm_mod

        original_ensure = LLMEngine._ensure_model

        def patched_ensure(self_engine):
            if self_engine._model is not None:
                return
            with self_engine._lock:
                if self_engine._model is not None:
                    return
                kwargs = {
                    "model_path": self_engine.config.model_path,
                    "n_ctx": self_engine.config.n_ctx,
                    "n_gpu_layers": self_engine.config.n_gpu_layers,
                    "verbose": False,
                    "flash_attn": self_engine.config.flash_attn,
                }
                if self_engine.config.type_k is not None:
                    kwargs["type_k"] = self_engine.config.type_k
                if self_engine.config.type_v is not None:
                    kwargs["type_v"] = self_engine.config.type_v
                self_engine._model = FakeLlama(**kwargs)
                captured_kwargs.update(kwargs)

        monkeypatch.setattr(LLMEngine, "_ensure_model", patched_ensure)

        config = LLMConfig(model_path="/fake.gguf", type_k=8, type_v=2, flash_attn=True)
        engine = LLMEngine(config=config)
        engine._ensure_model()

        assert captured_kwargs["type_k"] == 8
        assert captured_kwargs["type_v"] == 2
        assert captured_kwargs["flash_attn"] is True

    def test_ensure_model_omits_type_k_when_none(self, monkeypatch):
        """Verify type_k is NOT passed when None (preserving llama.cpp defaults)."""
        captured_kwargs = {}

        class FakeLlama:
            def __init__(self, **kw):
                captured_kwargs.update(kw)

        def patched_ensure(self_engine):
            if self_engine._model is not None:
                return
            with self_engine._lock:
                kwargs = {
                    "model_path": self_engine.config.model_path,
                    "n_ctx": self_engine.config.n_ctx,
                    "n_gpu_layers": self_engine.config.n_gpu_layers,
                    "verbose": False,
                    "flash_attn": self_engine.config.flash_attn,
                }
                if self_engine.config.type_k is not None:
                    kwargs["type_k"] = self_engine.config.type_k
                if self_engine.config.type_v is not None:
                    kwargs["type_v"] = self_engine.config.type_v
                self_engine._model = FakeLlama(**kwargs)
                captured_kwargs.update(kwargs)

        monkeypatch.setattr(LLMEngine, "_ensure_model", patched_ensure)

        config = LLMConfig(model_path="/fake.gguf")  # type_k=None, type_v=None
        engine = LLMEngine(config=config)
        engine._ensure_model()

        assert "type_k" not in captured_kwargs
        assert "type_v" not in captured_kwargs
