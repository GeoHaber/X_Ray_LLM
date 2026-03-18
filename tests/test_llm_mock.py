"""
LLM Mock Tests — verify generate_test, generate_fix, analyze_codebase
work correctly with mocked model responses.

Run:  python -m pytest tests/test_llm_mock.py -v --tb=short
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from xray.llm import LLMConfig, LLMEngine


def _make_engine_with_mock():
    """Create an LLMEngine with a mocked model that returns predictable responses."""
    config = LLMConfig(model_path="/fake/model.gguf")
    engine = LLMEngine(config=config)

    # Mock the model
    mock_model = MagicMock()
    mock_model.create_chat_completion.return_value = {
        "choices": [
            {"message": {"content": "MOCK_RESPONSE"}}
        ]
    }
    engine._model = mock_model
    return engine, mock_model


# ═════════════════════════════════════════════════════════════════════════════
# 1. generate() basics
# ═════════════════════════════════════════════════════════════════════════════

class TestGenerate:
    """Test the raw generate() method with mocked model."""

    def test_generate_returns_string(self):
        engine, mock = _make_engine_with_mock()
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
        engine, mock = _make_engine_with_mock()
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
        user_msg = [m for m in messages if m["role"] == "user"][0]["content"]
        assert "SEC-003" in user_msg
        assert "shell=True" in user_msg

    def test_system_prompt_mentions_pytest(self):
        engine, mock = _make_engine_with_mock()
        finding = {"rule_id": "X", "severity": "LOW", "description": "x",
                   "file": "x.py", "line": 1, "test_hint": "x"}
        engine.generate_test(finding, "ctx")
        call_args = mock.create_chat_completion.call_args
        messages = call_args[1].get("messages", [])
        system_msg = [m for m in messages if m["role"] == "system"][0]["content"]
        assert "pytest" in system_msg


# ═════════════════════════════════════════════════════════════════════════════
# 3. generate_fix()
# ═════════════════════════════════════════════════════════════════════════════

class TestGenerateFix:
    """Test the generate_fix() method."""

    def test_returns_string(self):
        engine, mock = _make_engine_with_mock()
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
        user_msg = [m for m in messages if m["role"] == "user"][0]["content"]
        assert "Use .get() with default" in user_msg

    def test_includes_test_error_when_provided(self):
        engine, mock = _make_engine_with_mock()
        finding = {"rule_id": "X", "severity": "LOW", "description": "x",
                   "fix_hint": "fix", "file": "x.py", "line": 1}
        engine.generate_fix(finding, "ctx", test_error="AssertionError: x != y")
        call_args = mock.create_chat_completion.call_args
        messages = call_args[1].get("messages", [])
        user_msg = [m for m in messages if m["role"] == "user"][0]["content"]
        assert "AssertionError" in user_msg

    def test_no_test_error_omits_section(self):
        engine, mock = _make_engine_with_mock()
        finding = {"rule_id": "X", "severity": "LOW", "description": "x",
                   "fix_hint": "fix", "file": "x.py", "line": 1}
        engine.generate_fix(finding, "ctx", test_error="")
        call_args = mock.create_chat_completion.call_args
        messages = call_args[1].get("messages", [])
        user_msg = [m for m in messages if m["role"] == "user"][0]["content"]
        assert "previous fix attempt" not in user_msg


# ═════════════════════════════════════════════════════════════════════════════
# 4. analyze_codebase()
# ═════════════════════════════════════════════════════════════════════════════

class TestAnalyzeCodebase:
    """Test the analyze_codebase() method."""

    def test_returns_string(self):
        engine, mock = _make_engine_with_mock()
        result = engine.analyze_codebase("5 HIGH, 3 MEDIUM findings")
        assert isinstance(result, str)

    def test_system_prompt_mentions_auditor(self):
        engine, mock = _make_engine_with_mock()
        engine.analyze_codebase("summary")
        call_args = mock.create_chat_completion.call_args
        messages = call_args[1].get("messages", [])
        system_msg = [m for m in messages if m["role"] == "system"][0]["content"]
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
