"""Redis 客户端：同步（发布/订阅）与异步（FastAPI 会话/限流）。

所有客户端都设置了 2 秒连接/读写超时并关闭超时重试：
Redis 不可达时快速失败，而不是让请求线程卡在 TCP 超时上。
"""
from typing import Optional

import redis
import redis.asyncio as aioredis

from app.core.config import settings

# 快速失败参数：连接与读写都限 2 秒，超时不重试
_SOCKET_TIMEOUT = 2
_COMMON_KWARGS = {
    "decode_responses": True,
    "socket_connect_timeout": _SOCKET_TIMEOUT,
    "socket_timeout": _SOCKET_TIMEOUT,
    "retry_on_timeout": False,
    "health_check_interval": 30,
}

_sync: Optional[redis.Redis] = None
_async: Optional[aioredis.Redis] = None


def get_redis() -> redis.Redis:
    global _sync
    if _sync is None:
        _sync = redis.Redis.from_url(settings.redis_url, **_COMMON_KWARGS)
    return _sync


def get_async_redis() -> aioredis.Redis:
    global _async
    if _async is None:
        _async = aioredis.from_url(settings.redis_url, **_COMMON_KWARGS)
    return _async


async def close_redis() -> None:
    global _async
    if _async is not None:
        await _async.aclose()
        _async = None
