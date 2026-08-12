"""QuantFlow M5-2 性能压测脚本（本地运行，后端需已启动）。

用法：
    cd backend && .venv/bin/python scripts/load_test.py [--base http://127.0.0.1:8000] [--concurrency 20] [--iterations 50]

覆盖：
1. API 延迟：/api/health、/api/workflows 并发请求，统计 P50/P95/P99；
2. 并发回测：目标 ≥20 并发 POST /api/backtest/run（buy_hold，1 年区间），统计成功率与耗时。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import statistics
import time
import urllib.request


def http_request(base: str, path: str, method: str = "GET", body: str | None = None) -> tuple[int, float]:
    url = base + path
    req = urllib.request.Request(url, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, data=body.encode() if body else None, timeout=60) as resp:
            status = resp.status
    except Exception as exc:  # noqa: BLE001
        status = getattr(exc, "code", 0)
    return status, time.perf_counter() - t0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * p))
    return ordered[idx]


def run_latency_test(base: str, concurrency: int, iterations: int) -> None:
    paths = ["/api/health", "/api/workflows"]
    print(f"\n== API 延迟（concurrency={concurrency}, iterations={iterations}）==")
    for path in paths:
        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            for _ in range(iterations):
                futures.append(pool.submit(http_request, base, path))
        results = [f.result() for f in futures]
        latencies = [r[1] for r in results]
        errors = [r for r in results if r[0] != 200]
        print(
            f"  {path}: "
            f"P50={percentile(latencies, .5)*1000:.1f}ms "
            f"P95={percentile(latencies, .95)*1000:.1f}ms "
            f"P99={percentile(latencies, .99)*1000:.1f}ms "
            f"max={max(latencies)*1000:.1f}ms | "
            f"{len(results)-len(errors)}/{len(results)} OK"
        )


def run_backtest_concurrency(base: str, concurrency: int) -> None:
    body = (
        '{"symbols":["TEST.STOCK"],"strategy":"buy_hold",'
        '"start":"2024-01-01","end":"2024-12-31","initial_cash":1000000}'
    )
    print(f"\n== 并发回测（concurrency={concurrency}，目标 ≥20）==")
    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(http_request, base, "/api/backtest/run", "POST", body) for _ in range(concurrency)]
        results = [f.result() for f in futures]
    wall = time.perf_counter() - t0
    statuses = [r[0] for r in results]
    latencies = [r[1] for r in results]
    ok = sum(1 for s in statuses if s == 200)
    print(f"  成功 {ok}/{concurrency}，总耗时 {wall:.2f}s")
    if latencies:
        print(
            f"  单请求 P50={percentile(latencies, .5)*1000:.0f}ms "
            f"P95={percentile(latencies, .95)*1000:.0f}ms "
            f"max={max(latencies)*1000:.0f}ms"
        )
    assert ok == concurrency, f"并发回测存在失败：{statuses}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--iterations", type=int, default=50)
    args = parser.parse_args()

    print(f"目标后端：{args.base}")
    try:
        http_request(args.base, "/api/health")
    except Exception:  # noqa: BLE001
        print("后端不可达，请先启动 uvicorn（QF_MARKET_PROVIDER=fixture）")
        raise SystemExit(1)

    run_latency_test(args.base, args.concurrency, args.iterations)
    run_backtest_concurrency(args.base, args.concurrency)
    print("\n== 压测通过 ==")


if __name__ == "__main__":
    main()
