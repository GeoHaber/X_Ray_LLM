import os
import json
import urllib.request
import urllib.error
from typing import Optional, Dict, Any
import asyncio
from .utils import logger, url_responds
from .config import LLM_CONFIG, load_llm_config

# Merge persisted settings on import
load_llm_config()


class LLMHelper:
    """Helper for interacting with local LLM APIs (OpenAI compatible)."""

    def __init__(
        self,
        root: Any = None,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        # Load from explicit args > env vars > config defaults
        self.base_url = base_url or os.getenv("LLM_BASE_URL", LLM_CONFIG["base_url"])
        self.api_key = api_key or os.getenv("LLM_API_KEY", LLM_CONFIG["api_key"])
        self.model = model or os.getenv("LLM_MODEL", LLM_CONFIG["model"])

    @property
    def available(self) -> bool:
        """Check if the LLM server is reachable."""
        if getattr(self, "_force_unavailable", False):
            return False
        return url_responds(f"{self.base_url}/models", timeout=2)

    def query_sync(self, prompt: str, **kwargs) -> str:
        """Synchronous query wrapper. Raises RuntimeError if LLM is not available."""
        if not self.available:
            raise RuntimeError("LLM not available")
        return self.completion(prompt, **kwargs)

    def completion(self, prompt: str, system_prompt: str = "") -> str:
        """Get a completion from the LLM."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": self.model,
            "messages": messages,
            "temperature": LLM_CONFIG["temperature"],
            "max_tokens": LLM_CONFIG["max_tokens"],
        }

        for attempt in range(1, 4):
            result = self._attempt_request(url, data, headers, attempt)
            if result is not None:
                return result
        return ""

    def _attempt_request(
        self, url: str, data: dict, headers: dict, attempt: int
    ) -> Optional[str]:
        """Execute a single LLM request attempt, returning text or *None* to retry."""
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=LLM_CONFIG["timeout"]) as response:  # noqa: S310  # nosec B310
                if response.status == 200:
                    result = json.loads(response.read().decode("utf-8"))
                    return result["choices"][0]["message"]["content"]
                logger.error(f"LLM API Error: {response.status}")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                self._backoff(attempt, f"LLM Error {e.code}")
                return None
            logger.error(f"LLM API HTTP Error: {e.code} - {e.reason}")
        except urllib.error.URLError as e:
            if attempt < 3:
                self._backoff(attempt, f"LLM Connection Failed: {e}")
                return None
            logger.error(f"LLM Connection Failed after retries: {e}")
        except Exception as e:
            logger.error(f"LLM Helper Unexpected Error: {e}")
        return ""

    @staticmethod
    def _backoff(attempt: int, reason: str) -> None:
        """Sleep with exponential back-off and log the retry reason."""
        import time

        wait = 2**attempt
        logger.warning(f"{reason}, retrying in {wait}s...")
        time.sleep(wait)

    async def completion_async(self, prompt: str, system_prompt: str = "") -> str:
        """
        Async version of completion using threads for blocking I/O.
        """
        return await asyncio.to_thread(self.completion, prompt, system_prompt)

    def generate_json(self, prompt: str, schema: Optional[Dict] = None) -> Any:
        """
        Generates JSON output from the LLM.
        """
        system_prompt = "You are a helpful assistant that outputs only valid JSON."
        full_prompt = prompt + "\n\nRespond with ONLY the JSON object/list."

        response = self.completion(full_prompt, system_prompt)
        return self._parse_json_response(response)

    async def generate_json_async(
        self, prompt: str, schema: Optional[Dict] = None
    ) -> Any:
        """
        Async version of generate_json.
        """
        system_prompt = "You are a helpful assistant that outputs only valid JSON."
        full_prompt = prompt + "\n\nRespond with ONLY the JSON object/list."

        response = await self.completion_async(full_prompt, system_prompt)
        return self._parse_json_response(response)

    def _parse_json_response(self, response: str) -> Any:
        """Strip markdown fences and parse JSON from an LLM response."""
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse JSON from LLM: {response[:100]}...")
            return None


async def _llm_enrich_one(prompt: str, on_result, llm, sem):
    """Shared async helper: send *prompt* to *llm* under *sem* and deliver result.

    *on_result* is called with the stripped response string on success.
    Any exception is silently logged at DEBUG level.
    """
    async with sem:
        try:
            resp = await llm.completion_async(prompt)
            on_result(resp.strip())
        except Exception as e:
            logger.debug("LLM enrichment failed: %s", e)


# Module-level API for test compatibility
_default_analyzer = LLMHelper()


def available():
    """Wrapper for LLMHelper.available property."""
    return _default_analyzer.available


def completion(*args, **kwargs):
    """Wrapper for LLMHelper.completion()."""
    return _default_analyzer.completion(*args, **kwargs)


def completion_async(*args, **kwargs):
    """Wrapper for LLMHelper.completion_async()."""
    return _default_analyzer.completion_async(*args, **kwargs)


def generate_json(*args, **kwargs):
    """Wrapper for LLMHelper.generate_json()."""
    return _default_analyzer.generate_json(*args, **kwargs)


def generate_json_async(*args, **kwargs):
    """Wrapper for LLMHelper.generate_json_async()."""
    return _default_analyzer.generate_json_async(*args, **kwargs)


def query_sync(*args, **kwargs):
    """Wrapper for LLMHelper.query_sync()."""
    return _default_analyzer.query_sync(*args, **kwargs)
