"""因子分析器：把统计量 / 分层收益 / 因子自相关组合成完整因子报告。

V1.1 N3 顶层入口，供 REST API 与节点复用。
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from .stats import ic_decay, ic_series, ic_summary, rank_ic


class FactorAnalyzer:
    """对一张「因子 + 下期收益」宽表做系统化因子分析。

    输入表需包含因子列、下期收益列；可选 date 列做截面分组。
    """

    def analyze(
        self,
        df: pd.DataFrame,
        factor_col: str,
        ret_col: str,
        date_col: Optional[str] = None,
        n_quantiles: int = 5,
        max_lag: int = 5,
    ) -> Dict:
        if factor_col not in df.columns:
            raise ValueError(f"缺少因子列: {factor_col}")
        if ret_col not in df.columns:
            raise ValueError(f"缺少收益列: {ret_col}")

        series = ic_series(df, factor_col, ret_col, date_col)
        ics = [ic for _, ic in series if ic is not None]
        summary = ic_summary(ics)
        decay = ic_decay(df, factor_col, ret_col, date_col, max_lag)
        quantiles = self._quantile_returns(df, factor_col, ret_col, date_col, n_quantiles)
        autocorr = self._factor_autocorrelation(df, factor_col, date_col)

        return {
            "ic": {
                "series": [{"date": d, "ic": ic} for d, ic in series],
                "mean": summary["mean"],
                "std": summary["std"],
                "ir": summary["ir"],
                "t_stat": summary["t_stat"],
                "pct_positive": summary["pct_positive"],
                "n": summary["n"],
            },
            "ic_decay": decay,
            "quantile_returns": quantiles,
            "factor_autocorrelation": autocorr,
            "n_quantiles": n_quantiles,
        }

    # ------------------------------------------------------------------ #
    def _quantile_returns(
        self,
        df: pd.DataFrame,
        factor_col: str,
        ret_col: str,
        date_col: Optional[str],
        n: int,
    ) -> Dict:
        """分层收益：逐截面按因子分位，统计各分位平均下期收益，多空 = 最高 - 最低分位。"""
        data = df.dropna(subset=[factor_col, ret_col]).copy()
        if n < 2:
            n = 2
        if date_col and date_col in data.columns:
            groups = data.groupby(date_col)
        else:
            groups = [("", data)]

        q_means: Dict[int, List[float]] = {q: [] for q in range(n)}
        for _, sub in groups:
            sub = sub.copy()
            size = max(1, len(sub) // n)
            # 按因子排名分桶（避免 qcut 在小样本上因分位边界不足而报错）
            sub["_q"] = ((sub[factor_col].rank(method="first") - 1) // size).clip(upper=n - 1)
            for q in range(n):
                m = sub.loc[sub["_q"] == q, ret_col].mean()
                if pd.notna(m):
                    q_means[q].append(float(m))

        by_quantile = {
            f"q{q + 1}": (sum(v) / len(v) if v else None)
            for q, v in q_means.items()
        }
        long_short = None
        if by_quantile["q1"] is not None and by_quantile[f"q{n}"] is not None:
            long_short = by_quantile[f"q{n}"] - by_quantile["q1"]
        return {"by_quantile": by_quantile, "long_short": long_short}

    def _factor_autocorrelation(
        self, df: pd.DataFrame, factor_col: str, date_col: Optional[str]
    ) -> Optional[float]:
        """因子自相关：相邻交易日截面因子排名的 RankIC（pooled 近似），衡量因子稳定性。"""
        if not (date_col and date_col in df.columns):
            return None
        data = df.dropna(subset=[factor_col]).copy()
        dates = sorted(data[date_col].astype(str).unique())
        ics: List[float] = []
        for i in range(len(dates) - 1):
            d0, d1 = dates[i], dates[i + 1]
            f0 = data.loc[data[date_col].astype(str) == d0, factor_col]
            f1 = data.loc[data[date_col].astype(str) == d1, factor_col]
            vals = pd.concat([f0, f1], axis=1).dropna()
            if len(vals) >= 3:
                ic = rank_ic(vals.iloc[:, 0], vals.iloc[:, 1])
                if ic is not None:
                    ics.append(ic)
        if not ics:
            return None
        return sum(ics) / len(ics)


def quick_factor_report(
    df: pd.DataFrame,
    factor_col: str,
    ret_col: str,
    date_col: Optional[str] = None,
    n_quantiles: int = 5,
    max_lag: int = 5,
) -> Dict:
    """便捷函数：直接产出因子报告。"""
    return FactorAnalyzer().analyze(
        df, factor_col, ret_col, date_col, n_quantiles, max_lag
    )
