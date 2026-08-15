"""自定义基准持久化存储（V26，无凭证）。

把用户自定义的基准定义（命名 + symbols/weights 或显式序列）落盘为 JSON，
支持保存 / 列举 / 读取 / 删除，便于在「基准对比」等场景复用，避免重复填写。
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional

DEFAULT_BENCHMARK_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "benchmarks"
)


class BenchmarkStore:
    """命名基准本地存储（落盘 JSON）。"""

    benchmark_dir: str = DEFAULT_BENCHMARK_DIR

    def save(self, benchmark: Dict[str, Any]) -> str:
        """保存基准定义，返回 bench_id。"""
        os.makedirs(self.benchmark_dir, exist_ok=True)
        bench_id = benchmark.get("bench_id") or uuid.uuid4().hex[:12]
        record = dict(benchmark)
        record["bench_id"] = bench_id
        path = os.path.join(self.benchmark_dir, f"{bench_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        return bench_id

    def load(self, bench_id: str) -> Dict[str, Any]:
        path = os.path.join(self.benchmark_dir, f"{bench_id}.json")
        if not os.path.exists(path):
            raise FileNotFoundError(f"基准不存在: {bench_id}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def list(self) -> List[str]:
        if not os.path.isdir(self.benchmark_dir):
            return []
        return sorted(
            p.replace(".json", "")
            for p in os.listdir(self.benchmark_dir)
            if p.endswith(".json")
        )

    def delete(self, bench_id: str) -> bool:
        path = os.path.join(self.benchmark_dir, f"{bench_id}.json")
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def summarize(self) -> List[Dict[str, Any]]:
        """列举全部基准的摘要（不含大体积显式序列）。"""
        out = []
        for bid in self.list():
            try:
                rec = self.load(bid)
            except Exception:
                continue
            syms = rec.get("symbols") or []
            has_values = bool(rec.get("values"))
            out.append({
                "bench_id": rec.get("bench_id"),
                "name": rec.get("name", rec.get("bench_id")),
                "symbols": syms,
                "weights": rec.get("weights"),
                "mode": "explicit" if has_values else "basket",
                "created_at": rec.get("created_at"),
            })
        return out


benchmark_store = BenchmarkStore()
