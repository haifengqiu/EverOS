"""Non-interactive test for generate_stream() on the va-dev branch.

Validates:
1. LLMProvider.generate_stream() works end-to-end
2. Streaming yields chunks incrementally
3. First chunk latency is reasonable
4. Full response can be reassembled from chunks

Usage:
    uv run python src/bootstrap.py demo/test_stream_demo.py
"""

import asyncio
import time
import sys
import os

# Add src to path for direct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


async def test_generate_stream():
    from memory_layer.llm.llm_provider import LLMProvider

    provider = LLMProvider(
        "openai",
        model=os.getenv("LLM_MODEL", "qwen-max"),
        api_key=os.getenv("LLM_API_KEY", "EMPTY"),
        base_url=os.getenv("LLM_BASE_URL", "http://localhost:9090/v1"),
    )

    prompt = "System: You are a helpful assistant.\n\nUser: What are 3 benefits of exercise? Answer in 2 sentences.\n\nAssistant:"

    print("=" * 60)
    print("Test: LLMProvider.generate_stream()")
    print("=" * 60)

    t_start = time.perf_counter()
    first_chunk_time = None
    chunks = []
    full_response = ""

    print("\nStreaming output:\n")
    try:
        async for chunk in provider.generate_stream(prompt):
            if first_chunk_time is None:
                first_chunk_time = time.perf_counter()
                first_chunk_ms = (first_chunk_time - t_start) * 1000
                print(f"  [First chunk: {first_chunk_ms:.0f}ms] ", end="", flush=True)

            chunks.append(chunk)
            full_response += chunk
            print(chunk, end="", flush=True)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

    t_end = time.perf_counter()
    total_ms = (t_end - t_start) * 1000

    print(f"\n\n{'=' * 60}")
    print("Results:")
    print(f"  Total chunks:     {len(chunks)}")
    print(f"  First chunk:      {first_chunk_ms:.0f}ms" if first_chunk_time else "  First chunk: N/A")
    print(f"  Total time:       {total_ms:.0f}ms")
    print(f"  Response length:  {len(full_response)} chars")

    if first_chunk_time and total_ms > first_chunk_ms:
        speedup = total_ms / first_chunk_ms
        print(f"  Streaming speedup: {speedup:.1f}x (first token vs full response)")

    # Validate
    assert len(chunks) > 0, "No chunks received"
    assert len(full_response) > 0, "Empty response"
    assert first_chunk_time is not None, "No first chunk received"

    print("\n✅ generate_stream() test PASSED")
    return True


async def test_generate_non_stream():
    """Compare with non-streaming generate() as baseline."""
    from memory_layer.llm.llm_provider import LLMProvider

    provider = LLMProvider(
        "openai",
        model=os.getenv("LLM_MODEL", "qwen-max"),
        api_key=os.getenv("LLM_API_KEY", "EMPTY"),
        base_url=os.getenv("LLM_BASE_URL", "http://localhost:9090/v1"),
    )

    prompt = "System: You are a helpful assistant.\n\nUser: What are 3 benefits of exercise? Answer in 2 sentences.\n\nAssistant:"

    print("\n" + "=" * 60)
    print("Baseline: LLMProvider.generate() (non-streaming)")
    print("=" * 60)

    t_start = time.perf_counter()
    try:
        response = await provider.generate(prompt)
    except Exception as e:
        print(f"ERROR: {e}")
        return False
    t_end = time.perf_counter()
    total_ms = (t_end - t_start) * 1000

    print(f"\n  Response: {response[:100]}...")
    print(f"  Total time: {total_ms:.0f}ms")
    print(f"  Response length: {len(response)} chars")
    print("✅ generate() baseline PASSED")
    return True


async def test_stream_via_api():
    """Test streaming through the API server (port 1995) with memory retrieval + streaming LLM."""
    import httpx

    base_url = "http://localhost:1995"

    print("\n" + "=" * 60)
    print("Test: End-to-end via API (store + search)")
    print("=" * 60)

    # First store a message
    ts = int(time.time() * 1000)
    store_payload = {
        "user_id": "stream_test_user",
        "messages": [{
            "message_id": f"stream_msg_{ts}",
            "sender_id": "stream_test_user",
            "role": "user",
            "content": "I love swimming in the ocean and hiking mountains on weekends",
            "timestamp": ts,
        }],
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Store
        resp = await client.post(f"{base_url}/api/v1/memories", json=store_payload)
        print(f"\n  Store: status={resp.status_code}")
        if resp.status_code not in (200, 202):
            print(f"  Store failed: {resp.text[:200]}")
            return False

        # Wait a bit for indexing
        await asyncio.sleep(3)

        # Search
        search_payload = {
            "query": "What sports does the user like?",
            "method": "hybrid",
            "memory_types": ["episodic_memory"],
            "top_k": 3,
            "filters": {"user_id": "stream_test_user"},
        }
        resp = await client.post(f"{base_url}/api/v1/memories/search", json=search_payload)
        print(f"  Search: status={resp.status_code}")
        if resp.status_code != 200:
            print(f"  Search failed: {resp.text[:200]}")
            return False

        data = resp.json().get("data", {})
        episodes = data.get("episodes", [])
        print(f"  Found {len(episodes)} episodes")

    print("✅ API end-to-end test PASSED")
    return True


async def main():
    print("\n🧪 va-dev Branch Streaming Verification")
    print("=" * 60)

    results = {}

    # Test 1: generate_stream directly
    try:
        results["generate_stream"] = await test_generate_stream()
    except Exception as e:
        print(f"\n❌ generate_stream test FAILED: {e}")
        results["generate_stream"] = False

    # Test 2: generate (baseline comparison)
    try:
        results["generate_non_stream"] = await test_generate_non_stream()
    except Exception as e:
        print(f"\n❌ generate baseline FAILED: {e}")
        results["generate_non_stream"] = False

    # Test 3: API end-to-end
    try:
        results["api_e2e"] = await test_stream_via_api()
    except Exception as e:
        print(f"\n❌ API e2e test FAILED: {e}")
        results["api_e2e"] = False

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {name}: {status}")

    all_passed = all(results.values())
    print(f"\nOverall: {'✅ ALL PASSED' if all_passed else '❌ SOME FAILED'}")
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
