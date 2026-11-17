import hashlib
from abc import ABC, abstractmethod
from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis


class LoginLimiter(ABC):
    @abstractmethod
    async def allow(self, username: str, address: str) -> bool: ...


class RedisLoginLimiter(LoginLimiter):
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def allow(self, username: str, address: str) -> bool:
        for value, limit in ((address, 50), (address + ":" + username, 10)):
            key = "login-limit:" + hashlib.sha256(value.encode()).hexdigest()
            count = await cast(
                Awaitable[int],
                self._redis.eval(
                    "local n=redis.call('INCR',KEYS[1]); "
                    "if n==1 then redis.call('EXPIRE',KEYS[1],900) end; return n",
                    1,
                    key,
                ),
            )
            if int(count) > limit:
                return False
        return True
