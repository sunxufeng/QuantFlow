"""因子库持久化（V1.1 N3）。

把因子定义（名称 / 类别 / 表达式 / 参数）落库到 SQLite ``factor_library`` 表，
支持增删改查，供工作流节点与因子分析页复用。与 :mod:`app.factors` 的计算逻辑解耦：
本模块只负责「定义的管理」，计算仍走 ``app.factors`` 的表达式引擎。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..core.db import db

_COLUMNS = (
    "id", "name", "category", "expression", "description",
    "params", "owner_id", "created_at", "updated_at",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> Dict:
    d = {k: row[k] for k in _COLUMNS}
    try:
        d["params"] = json.loads(row["params"]) if row["params"] else {}
    except (json.JSONDecodeError, TypeError):
        d["params"] = {}
    return d


def create_factor(
    name: str,
    expression: str,
    category: str = "自定义",
    description: str = "",
    params: Optional[Dict] = None,
    owner_id: Optional[str] = None,
) -> Dict:
    """新建因子定义。"""
    fid = f"fac_{uuid.uuid4().hex[:12]}"
    now = _now()
    with db._lock:
        db._ensure().execute(
            "INSERT INTO factor_library "
            "(id, name, category, expression, description, params, owner_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fid, name, category, expression, description,
                json.dumps(params or {}, ensure_ascii=False),
                owner_id, now, now,
            ),
        )
        db._ensure().commit()
    return get_factor(fid)


def list_factors(owner_id: Optional[str] = None, category: Optional[str] = None) -> List[Dict]:
    """列出因子定义；可过滤 owner / category（缺省不过滤）。

    当传入 ``owner_id`` 时，返回「该用户自己的 + 全局内置（owner_id IS NULL）」，
    便于用户既能管理自己的因子，也能看到并复用内置因子模板。
    """
    sql = "SELECT {} FROM factor_library".format(", ".join(_COLUMNS))
    clauses: List[str] = []
    params: List[str] = []
    if owner_id is not None:
        clauses.append("(owner_id = ? OR owner_id IS NULL)")
        params.append(owner_id)
    if category is not None:
        clauses.append("category = ?")
        params.append(category)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY updated_at DESC"
    rows = db.query(sql, params)
    return [_row_to_dict(r) for r in rows]


def get_factor(factor_id: str) -> Optional[Dict]:
    row = db.query_one(
        "SELECT {} FROM factor_library WHERE id = ?".format(", ".join(_COLUMNS)),
        (factor_id,),
    )
    return _row_to_dict(row) if row else None


def update_factor(factor_id: str, **changes) -> Optional[Dict]:
    """局部更新因子定义（name/category/expression/description/params）。"""
    allowed = {"name", "category", "expression", "description", "params"}
    fields = {k: v for k, v in changes.items() if k in allowed and v is not None}
    if not fields:
        return get_factor(factor_id)
    if "params" in fields and not isinstance(fields["params"], str):
        fields["params"] = json.dumps(fields["params"], ensure_ascii=False)
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with db._lock:
        db._ensure().execute(
            f"UPDATE factor_library SET {set_clause} WHERE id = ?",
            tuple(fields.values()) + (factor_id,),
        )
        db._ensure().commit()
    return get_factor(factor_id)


def delete_factor(factor_id: str) -> bool:
    with db._lock:
        cur = db._ensure().execute("DELETE FROM factor_library WHERE id = ?", (factor_id,))
        db._ensure().commit()
    return cur.rowcount > 0


def seed_defaults() -> int:
    """首次启动时写入内置因子库（动量 / 反转 / 波动率 / 风险 / 技术 / 量价 等）。

    按 ``name`` 幂等：仅补充缺失的内置因子，已存在则跳过，便于版本升级时增量扩充。
    """
    existing = {f["name"] for f in list_factors()}
    presets = [
        ("动量因子(20日)", "动量", "close.pct_change(20)", "近 20 日收益率", {"period": 20}),
        ("反转因子(5日)", "反转", "close.pct_change(5) * -1", "近 5 日收益取反", {"period": 5}),
        ("波动率因子", "风险", "close.pct_change().rolling(20).std()", "20 日收益率标准差", {"window": 20}),
        ("市值因子(成交额)", "基本面", "close * volume", "收盘价×成交量，代理规模/流动性", {}),
        ("RSI因子(14日)", "技术", "close.pct_change().clip(lower=0).rolling(14).mean() / (close.pct_change().abs().rolling(14).mean()+1e-9)", "相对强弱，越接近 1 越超买", {"period": 14}),
        ("MACD柱因子", "技术", "close.ewm(span=12).mean() - close.ewm(span=26).mean()", "快慢 EMA 差值，动量强弱", {"fast": 12, "slow": 26}),
        ("换手率因子", "量价", "volume / volume.rolling(20).mean()", "成交量相对 20 日均量，放量程度", {"window": 20}),
        ("低波因子", "风险", "-close.pct_change().rolling(20).std()", "20 日波动取反，越低波越好", {"window": 20}),
        ("乖离率因子", "技术", "(close - close.rolling(20).mean())/close.rolling(20).mean()", "价格相对 20 日均线偏离", {"window": 20}),
        ("量价共振因子", "量价", "close.pct_change(5) * (volume / volume.rolling(20).mean())", "近 5 日收益与放量程度乘积", {"period": 5, "window": 20}),
    ]
    added = 0
    for name, cat, expr, desc, params in presets:
        if name in existing:
            continue
        create_factor(name, expr, cat, desc, params)
        added += 1
    return added
