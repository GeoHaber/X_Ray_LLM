
import os
import json
import urllib.request
import urllib.error
from typing import Optional, Dict, Any
import asyncio
from .utils import logger
from .config import LLM_CONFIG

class LLMHelper:
    """Helper for interacting with local LLM APIs (OpenAI compatible)."""
    
    def __init__(self, root: Any = None, *, base_url: Optional[str] = None, api_key: Optional[str] = None, model: Optional[str] = None):
        # Load from explicit args > env vars > config defaults
        self.base_url = base_url or os.getenv("LLM_BASE_URL", LLM_CONFIG["base_url"])
        self.api_key = api_key or os.getenv("LLM_API_KEY", LLM_CONFIG["api_key"])
        self.model = model or os.getenv("LLM_MODEL", LLM_CONFIG["model"])

    @property
    def available(self) -> bool:
        """Check if the LLM server is reachable."""
        if getattr(self, '_force_unavailable', False):
            return False
        try:
            # Simple health check or models listing
            req = urllib.request.Request(f"{self.base_url}/models", method='GET')
            with urllib.request.urlopen(req, timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def query_sync(self, prompt: str, **kwargs) -> str:
        """Synchronous query wrapper. Raises RuntimeError if LLM is not available."""
        if not self.available:
            raise RuntimeError("LLM not available")
        return self.completion(prompt, **kwargs)

    def completion(self, prompt: str, system_prompt: str = "") -> str:
        """
        Get a completion from the LLM.
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": self.model,
            "messages": messages,
            "temperature": LLM_CONFIG["temperature"],
            "max_tokens": LLM_CONFIG["max_tokens"]
        }
        
        for attempt in range(1, 4):  # Try 3 times
            try:
                req = urllib.request.Request(
                    url, 
                    data=json.dumps(data).encode('utf-8'), 
                    headers=headers, 
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=LLM_CONFIG["timeout"]) as response:
                    if response.status == 200:
                        result = json.loads(response.read().decode('utf-8'))
                        return result["choices"][0]["message"]["content"]
                    logger.error(f"LLM API Error: {response.status}")
                    return ""
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                    wait_time = 2 ** attempt
                    logger.warning(f"LLM Error {e.code}, retrying in {wait_time}s...")
                    import time
                    time.sleep(wait_time)
                    continue
                logger.error(f"LLM API HTTP Error: {e.code} - {e.reason}")
                return ""
            except urllib.error.URLError as e:
                if attempt < 3:
                    wait_time = 2 ** attempt
                    logger.warning(f"LLM Connection Failed: {e}, retrying in {wait_time}s...")
                    import time
                    time.sleep(wait_time)
                    continue
                logger.error(f"LLM Connection Failed after retries: {e}")
                return ""
            except Exception as e:
                logger.error(f"LLM Helper Unexpected Error: {e}")
                return ""
        return ""

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
        
        # Simple cleanup
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

    async def generate_json_async(self, prompt: str, schema: Optional[Dict] = None) -> Any:
        """
        Async version of generate_json.
        """
        system_prompt = "You are a helpful assistant that outputs only valid JSON."
        full_prompt = prompt + "\n\nRespond with ONLY the JSON object/list."
        
        response = await self.completion_async(full_prompt, system_prompt)
        
        # Reuse parsing logic? Or just duplicate for simplicity to avoid separating logic
        # Clean up
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
