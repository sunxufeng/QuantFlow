"""行情缓存：Redis 优先，内存降级（M2 数据层）。

Redis 未启动 / 连接失败时自动回退内存缓存，保证平台可运行。
缓存键由服务层用 ``cache_key`` 生成，值为 JSON 序列化的 Bar 列表。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("quantflow.market.cache")


class CacheBackend:
    """缓存后端接口。"""

    name = "base"

    def get(self, key: str) -> Optional[Any]:  # pragma: no cover - 抽象
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl: int) -> None:  # pragma: no cover
        raise NotImplementedError


class MemoryCache(CacheBackend):
    """进程内 TTL 缓存（默认降级方案）。"""

    name = "memory"

    def __init__(self) -> None:
        self._store: Dict[str, tuple] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if item is None:
            return None
        value, expires = item
        if expires and time.time() > expires:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        # ttl < 0 表示立即过期（测试语义），ttl == 0 表示不过期
        if ttl < 0:
            expires = time.time() - 1
        else:
            expires = time.time() + ttl if ttl > 0 else 0
        self._store[key] = (value, expires)


class RedisCache(CacheBackend):
    """Redis 缓存；连接失败自动降级为 MemoryCache。"""

    name = "redis"

    def __init__(self, url: str, fallback_ttl: int = 3600) -> None:
        self._url = url
        self._ttl = fallback_ttl
        self._redis = None
        self._memory = MemoryCache()
        try:
            import redis  # 延迟导入
        except ImportError:
            logger.warning("redis 未安装，使用内存缓存")
            return
        try:
            self._redis = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
            self._redis.ping()
            logger.info("Redis 缓存已连接：%s", url)
        except Exception as exc:  # pragma: no cover - 依赖环境
            self._redis = None
            logger.warning("Redis 连接失败（%s），降级为内存缓存", exc)

    def get(self, key: str) -> Optional[Any]:
        if self._redis is None:
            return self._memory.get(key)
        try:
            raw = self._redis.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return self._memory.get(key)

    def set(self, key: str, value: Any, ttl: int) -> None:
        if self._redis is None:
            self._memory.set(key, value, ttl)
            return
        try:
            self._redis.setex(key, ttl or self._ttl, json.dumps(value, ensure_ascii=False))
        except Exception as exc:  # pragma: no cover - 依赖环境
            logger.warning("Redis 写入失败（%s），降级内存缓存", exc)
            self._memory.set(key, value, ttl)


def default_cache() -> CacheBackend:
    import os

    url = os.getenv("QF_REDIS_URI", "redis://localhost:6379")
    return RedisCache(url=url)
