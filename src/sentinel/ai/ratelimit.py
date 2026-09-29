"""Global LLM rate limiting (spec §16): a token bucket shared by all workers in Redis.

The bucket's state lives in Redis and is updated atomically by a Lua script using the
Redis server clock, so every worker process draws from one budget. If Redis is
unreachable the limiter degrades to a per-process bucket at a fraction of the rate:
throughput drops, correctness is unaffected (Redis never holds correctness state).
"""

import asyncio
import logging
import time

from redis.asyncio import Redis
from redis.exceptions import RedisError

from sentinel.config import get_settings

log = logging.getLogger("sentinel.ratelimit")

_TAKE = """
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local rate, capacity = tonumber(ARGV[1]), tonumber(ARGV[2])
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1]) or capacity
local ts = tonumber(state[2]) or now
tokens = math.min(capacity, tokens + math.max(0, now - ts) * rate)
local wait_ms = 0
if tokens >= 1 then tokens = tokens - 1 else wait_ms = math.ceil((1 - tokens) / rate * 1000) end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], 60)
return wait_ms
"""


class _LocalBucket:
    def __init__(self, rate: float, capacity: float) -> None:
        self.rate, self.capacity = rate, capacity
        self.tokens, self.ts = capacity, time.monotonic()

    def take(self) -> float:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.ts) * self.rate)
        self.ts = now
        if self.tokens >= 1:
            self.tokens -= 1
            return 0.0
        return (1 - self.tokens) / self.rate


class LLMRateLimiter:
    KEY = "sentinel:llm:bucket"

    def __init__(self, redis_url: str, rate: float, burst: int, fallback_fraction: float) -> None:
        self.rate, self.burst = rate, burst
        self._redis = Redis.from_url(redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
        self._script = self._redis.register_script(_TAKE)
        self._fallback = _LocalBucket(rate * fallback_fraction, max(1.0, burst * fallback_fraction))
        self._degraded = False

    @classmethod
    def from_settings(cls) -> "LLMRateLimiter":
        s = get_settings()
        return cls(str(s.redis_url), s.llm_rate_per_second, s.llm_burst, s.llm_fallback_fraction)

    async def acquire(self) -> dict[str, object]:
        """Wait for a token. Returns how long we waited and which limiter was used."""
        waited = 0.0
        while True:
            wait = await self._take()
            if wait <= 0:
                return {"rate_limit_wait_ms": round(waited * 1000), "limiter": self.mode}
            await asyncio.sleep(wait)
            waited += wait

    @property
    def mode(self) -> str:
        return "local-fallback" if self._degraded else "redis"

    async def _take(self) -> float:
        try:
            wait_ms = await self._script(keys=[self.KEY], args=[self.rate, self.burst])
        except (RedisError, OSError) as error:
            if not self._degraded:
                log.warning(
                    "redis unavailable; using local LLM rate limit", extra={"error": str(error)}
                )
            self._degraded = True
            return self._fallback.take()
        if self._degraded:
            log.info("redis available again; using shared LLM rate limit")
            self._degraded = False
        return float(wait_ms) / 1000
