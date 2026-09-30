import time

from sentinel.ai.ratelimit import LLMRateLimiter


async def test_redis_outage_falls_back_to_a_local_share_of_the_rate() -> None:
    # Nothing listens on port 1: every Redis call fails fast.
    limiter = LLMRateLimiter("redis://127.0.0.1:1/0", rate=40, burst=4, fallback_fraction=0.25)

    first = await limiter.acquire()
    assert first["limiter"] == "local-fallback"

    # Local bucket: burst 1, refilling at 40 * 0.25 = 10/s, so the next token waits ~0.1 s.
    started = time.monotonic()
    await limiter.acquire()
    assert 0.05 <= time.monotonic() - started < 0.5
