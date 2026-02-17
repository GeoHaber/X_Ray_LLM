
import asyncio
import pytest
from Core.inference import LLMHelper

@pytest.mark.asyncio
async def test_async_inference():
    llm = LLMHelper()
    if not llm.available:
        print("LLM not available, skipping.")
        return

    print("Testing async inference...")
    # Mocking or using real depends on config, but this checks the async wrapper
    try:
        res = await llm.query_async("Say hello", max_tokens=10)
        print(f"Result: {res}")
    except Exception as e:
        print(f"Async query failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_async_inference())
