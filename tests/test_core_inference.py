"""
Tests for Core/inference.py — LLMHelper.
Mocks all HTTP to avoid needing a running LLM server.
"""
import json
from unittest.mock import patch, MagicMock
from Core.inference import LLMHelper


# ── helpers ──────────────────────────────────────────────────────────

def _mock_urlopen(body_dict, status=200):
    """Return a context-manager mock that simulates urllib.request.urlopen."""
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = json.dumps(body_dict).encode("utf-8")
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# ════════════════════════════════════════════════════════════════════
#  __init__
# ════════════════════════════════════════════════════════════════════

class TestLLMHelperInit:

    def test_defaults(self):
        llm = LLMHelper()
        assert "localhost" in llm.base_url or llm.base_url.startswith("http")
        assert llm.model  # some model string

    def test_env_overrides(self):
        with patch.dict("os.environ", {
            "LLM_BASE_URL": "http://custom:9999/v1",
            "LLM_API_KEY": "sk-test",
            "LLM_MODEL": "gpt-test",
        }):
            llm = LLMHelper()
            assert llm.base_url == "http://custom:9999/v1"
            assert llm.api_key == "sk-test"
            assert llm.model == "gpt-test"

    def test_constructor_args(self):
        llm = LLMHelper(base_url="http://x:1/v1", api_key="k1")
        # Constructor now accepts base_url/api_key overrides
        assert llm.base_url == "http://x:1/v1"
        assert llm.api_key == "k1"


# ════════════════════════════════════════════════════════════════════
#  completion
# ════════════════════════════════════════════════════════════════════

class TestCompletion:
    """Tests for LLM completion method."""

    @patch("Core.inference.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({
            "choices": [{"message": {"content": "Hello world"}}]
        })
        llm = LLMHelper()
        result = llm.completion("say hello")
        assert result == "Hello world"

    @patch("Core.inference.urllib.request.urlopen")
    def test_with_system_prompt(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({
            "choices": [{"message": {"content": "sys ok"}}]
        })
        llm = LLMHelper()
        result = llm.completion("test", system_prompt="You are helpful")
        assert result == "sys ok"

    @patch("Core.inference.urllib.request.urlopen")
    def test_non_200_returns_empty(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({}, status=500)
        llm = LLMHelper()
        result = llm.completion("test")
        assert result == ""

    @patch("Core.inference.urllib.request.urlopen")
    def test_urlerror_returns_empty(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        llm = LLMHelper()
        result = llm.completion("test")
        assert result == ""

    @patch("Core.inference.urllib.request.urlopen")
    def test_generic_exception_returns_empty(self, mock_urlopen):
        mock_urlopen.side_effect = RuntimeError("boom")
        llm = LLMHelper()
        result = llm.completion("test")
        assert result == ""


# ════════════════════════════════════════════════════════════════════
#  generate_json
# ════════════════════════════════════════════════════════════════════

class TestGenerateJson:
    """Tests for LLM JSON generation."""

    @patch("Core.inference.urllib.request.urlopen")
    def test_valid_json(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({
            "choices": [{"message": {"content": '{"key": "value"}'}}]
        })
        llm = LLMHelper()
        result = llm.generate_json("make json")
        assert result == {"key": "value"}

    @patch("Core.inference.urllib.request.urlopen")
    def test_strips_json_fences(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({
            "choices": [{"message": {"content": '```json\n[1,2,3]\n```'}}]
        })
        llm = LLMHelper()
        result = llm.generate_json("make list")
        assert result == [1, 2, 3]

    @patch("Core.inference.urllib.request.urlopen")
    def test_strips_generic_fences(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({
            "choices": [{"message": {"content": '```\n{"a":1}\n```'}}]
        })
        llm = LLMHelper()
        result = llm.generate_json("x")
        assert result == {"a": 1}

    @patch("Core.inference.urllib.request.urlopen")
    def test_invalid_json_returns_none(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({
            "choices": [{"message": {"content": "not json at all"}}]
        })
        llm = LLMHelper()
        result = llm.generate_json("x")
        assert result is None

    @patch("Core.inference.urllib.request.urlopen")
    def test_empty_response_returns_none(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen({
            "choices": [{"message": {"content": ""}}]
        })
        llm = LLMHelper()
        result = llm.generate_json("x")
        assert result is None
