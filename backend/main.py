import os
import json
import hashlib
from datetime import datetime, timezone

import redis
import time
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from playwright.sync_api import sync_playwright

from parsers import (
    parse_plati,
    parse_playerok,
    parse_ggsel,
    group_all_items,
)

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
CACHE_TTL = int(os.getenv("CACHE_TTL", "1800"))  
CACHE_PREFIX = "agg:v1"

app = FastAPI(
    title="Game Keys Aggregator API",
    version="1.1.0",
    description="Сравнение цен: Plati.market / Playerok / Ggsel.net",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Cache", "X-Cache-Age"],
)


class AggregatorCache:
    """Кэш с graceful degradation: если Redis упал — парсим, не падаем."""

    def __init__(self, url: str):
        self.client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=False,
        )
        self.available = False
        self.ping()

    def ping(self) -> bool:
        try:
            self.client.ping()
            self.available = True
        except redis.RedisError:
            self.available = False
            print("⚠️ Redis недоступен. Работаю без кэша.")
        return self.available

    @staticmethod
    def make_key(query: str) -> str:
        normalized = " ".join(query.lower().split())
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
        return f"{CACHE_PREFIX}:search:{digest}"

    def get(self, query: str):
        if not self.available:
            return None
        try:
            raw = self.client.get(self.make_key(query))
            if not raw:
                return None
            return json.loads(raw)
        except (redis.RedisError, json.JSONDecodeError):
            return None

    def set(self, query: str, payload: dict, ttl: int = CACHE_TTL):
        if not self.available:
            return
        try:
            self.client.setex(
                self.make_key(query),
                ttl,
                json.dumps(payload, ensure_ascii=False),
            )
        except redis.RedisError as e:
            print(f"⚠️ Не удалось записать в кэш: {e}")


cache = AggregatorCache(REDIS_URL)


def collect_results(query: str) -> dict:
    with sync_playwright() as p:
        plati_raw = parse_plati(p, query)
        playerok_raw = parse_playerok(p, query)

    ggsel_raw = parse_ggsel(query)
    all_items = plati_raw + playerok_raw + ggsel_raw

    matched_groups, unique_items = group_all_items(all_items)

    return {
        "query": query,
        "total_found": len(all_items),
        "matched_groups": [
            {
                "base_title": group[0]["title"],
                "best_price": min(i["price_num"] for i in group),
                "offers": [
                    {
                        "source": i["source"],
                        "title": i["title"],
                        "price": i["price"],
                        "price_num": i["price_num"],
                        "url": i["url"],
                        "is_cheapest": i["price_num"]
                        == min(x["price_num"] for x in group),
                    }
                    for i in sorted(group, key=lambda x: x["price_num"])
                ],
            }
            for group in matched_groups
        ],
        "unique_items": [
            {
                "source": i["source"],
                "title": i["title"],
                "price": i["price"],
                "url": i["url"],
            }
            for i in unique_items
        ],
    }


@app.get("/")
def root():
    return {
        "status": "ok",
        "redis_connected": cache.available,
        "cache_ttl_seconds": CACHE_TTL,
        "docs": "/docs",
    }


@app.get("/api/search")
def search_items(
    query: str = Query(..., min_length=2, description="Название игры"),
    force_refresh: bool = Query(False, description="Игнорировать кэш и собрать заново"),
):
    normalized_query = " ".join(query.lower().split())
    
    if not force_refresh:
        cached = cache.get(normalized_query)
        if cached is not None:
            return JSONResponse(
                content={**cached, "cache": {"hit": True, "cached_at": cached.get("cached_at"), "ttl_seconds": CACHE_TTL}},
                headers={"X-Cache": "HIT"},
            )

    lock_key = f"{CACHE_PREFIX}:lock:{hashlib.sha256(normalized_query.encode('utf-8')).hexdigest()[:20]}"
    acquired = cache.client.set(lock_key, "1", nx=True, ex=30)
    
    if not acquired:
        time.sleep(2)
        cached_retry = cache.get(normalized_query)
        if cached_retry:
            return JSONResponse(
                content={**cached_retry, "cache": {"hit": True, "waited": True, "cached_at": cached_retry.get("cached_at")}},
                headers={"X-Cache": "HIT (after wait)"},
            )
        raise HTTPException(status_code=429, detail="Этот запрос уже обрабатывается. Пожалуйста, подождите пару секунд и обновите страницу.")

    try:
        payload = collect_results(query)
    except Exception as e:
        cache.client.delete(lock_key)
        
        stale = cache.get(normalized_query)
        if stale:
            return JSONResponse(content={**stale, "cache": {"hit": True, "stale": True}}, headers={"X-Cache": "STALE"})
        raise HTTPException(status_code=502, detail=f"Не удалось собрать данные: {e}")

    payload["cached_at"] = datetime.now(timezone.utc).isoformat()
    cache.set(normalized_query, payload)
    
    cache.client.delete(lock_key)

    return JSONResponse(
        content={**payload, "cache": {"hit": False, "cached_at": payload["cached_at"], "ttl_seconds": CACHE_TTL}},
        headers={"X-Cache": "MISS"},
    )


@app.delete("/api/cache")
def clear_cache(query: str | None = None):
    """Админ-метод: сбросить кэш конкретного запроса или всего приложения."""
    if not cache.available:
        raise HTTPException(status_code=503, detail="Redis недоступен")

    if query:
        cache.client.delete(cache.make_key(query))
        return {"deleted": cache.make_key(query)}

    keys = list(cache.client.scan_iter(match=f"{CACHE_PREFIX}:*"))
    if keys:
        cache.client.delete(*keys)
    return {"deleted_keys": len(keys)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)