"""
KPI計算ユーティリティ
"""
import pandas as pd


def latest_net(df: pd.DataFrame, investor_type: str, amount_col: str = "net_amount") -> float:
    """指定投資家の最新週NET金額を返す"""
    sub = df[df["investor_type"] == investor_type]
    if sub.empty:
        return 0.0
    return float(sub.sort_values("week_date").iloc[-1][amount_col])


def prev_net(df: pd.DataFrame, investor_type: str, amount_col: str = "net_amount") -> float:
    """指定投資家の前週NET金額を返す"""
    sub = df[df["investor_type"] == investor_type].sort_values("week_date")
    if len(sub) < 2:
        return 0.0
    return float(sub.iloc[-2][amount_col])


def wow_delta(current: float, previous: float) -> tuple[float, str, str]:
    """前週比を (差分, 矢印, 色) で返す"""
    delta = current - previous
    arrow = "↑" if delta >= 0 else "↓"
    color = "green" if delta >= 0 else "red"
    return delta, arrow, color


def format_oku(value: float) -> str:
    """億円表示フォーマット（例: +1,234億）"""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:,.0f}億"
