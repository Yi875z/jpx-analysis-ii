"""
scripts/analyze_jpx.py
Supabase蓄積データからZスコア・合算・月次集計を計算する
"""

import logging
from collections import defaultdict
from datetime import date
import numpy as np

logger = logging.getLogger(__name__)

INVESTORS = ["foreign", "individual", "trust_bank", "inv_trust", "corporate", "dealer"]
INVESTOR_JP = {
    "foreign":    "海外投資家",
    "individual": "個人投資家",
    "trust_bank": "信託銀行",
    "inv_trust":  "投資信託",
    "corporate":  "事業法人",
    "dealer":     "自己（証券会社）",
}


def calc_zscore(values: list[float], window: int) -> float | None:
    """過去window週のZスコアを計算"""
    if len(values) < window:
        return None
    arr = np.array(values[:window], dtype=float)
    mean, std = arr.mean(), arr.std()
    if std == 0:
        return 0.0
    return round(float((values[0] - mean) / std), 3)


def calc_ma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return round(float(np.mean(values[:window])), 2)


# ─────────────────────────────────────────
# 合算データ生成
# ─────────────────────────────────────────
def build_combined(spot_rows: list[dict], futures_rows: list[dict],
                   week_date: date) -> list[dict]:
    """現物＋先物換算の合算行を生成"""
    spot_map    = {r["investor_type"]: r.get("net_amount", 0) or 0 for r in spot_rows}
    futures_net = defaultdict(float)

    for r in futures_rows:
        oku = r.get("net_amount_oku") or 0
        futures_net[r["investor_type"]] += oku

    combined = []
    for inv in INVESTORS:
        s = spot_map.get(inv, 0) or 0
        f = futures_net.get(inv, 0) or 0
        combined_val = s + f

        # 両輪買い判定（現物・先物ともに買い越し）
        twin = (s > 0 and f > 0)

        combined.append({
            "week_date":     str(week_date),
            "investor_type": inv,
            "spot_net":      round(s, 2),
            "futures_net_oku": round(f, 2),
            "combined_net":  round(combined_val, 2),
            "is_twin_engine": twin,
        })

    return combined


# ─────────────────────────────────────────
# Zスコア・統計計算
# ─────────────────────────────────────────
def build_stats(week_date: date, db) -> list[dict]:
    """
    Supabaseの蓄積データからZスコア・前週比・4週MAを計算
    db: supabase_client モジュール
    """
    stats_rows = []

    for inv in INVESTORS:
        # 現物
        spot_hist = db.fetch_spot_history(inv, weeks=52)
        nets = [r["net_amount"] for r in spot_hist if r.get("net_amount") is not None]

        if nets:
            current = nets[0]
            prev    = nets[1] if len(nets) > 1 else None
            stats_rows.append({
                "week_date":     str(week_date),
                "investor_type": inv,
                "data_type":     "spot",
                "net_amount":    current,
                "zscore_26w":    calc_zscore(nets, 26),
                "zscore_52w":    calc_zscore(nets, 52),
                "ma4w":          calc_ma(nets, 4),
                "wow_change":    round(current - prev, 2) if prev is not None else None,
            })

        # 先物（全先物種別の合算）
        fut_hist = db.fetch_futures_history(inv, weeks=52)
        # week_dateごとに合算
        fut_by_week = defaultdict(float)
        for r in fut_hist:
            fut_by_week[r["week_date"]] += (r.get("net_amount_oku") or 0)
        fut_nets = [v for _, v in sorted(fut_by_week.items(), reverse=True)]

        if fut_nets:
            current_f = fut_nets[0]
            prev_f    = fut_nets[1] if len(fut_nets) > 1 else None
            stats_rows.append({
                "week_date":     str(week_date),
                "investor_type": inv,
                "data_type":     "futures",
                "net_amount":    current_f,
                "zscore_26w":    calc_zscore(fut_nets, 26),
                "zscore_52w":    calc_zscore(fut_nets, 52),
                "ma4w":          calc_ma(fut_nets, 4),
                "wow_change":    round(current_f - prev_f, 2) if prev_f is not None else None,
            })

    logger.info(f"[統計] {len(stats_rows)}件のZスコア計算完了")
    return stats_rows


# ─────────────────────────────────────────
# 月次サマリー計算
# ─────────────────────────────────────────
def build_monthly(year_month: str, db) -> list[dict]:
    """
    指定年月（YYYY-MM）の週次データを集計して月次サマリーを生成
    """
    import sys
    from supabase import Client

    sb = db.get_client()

    # 該当月の週次現物を取得
    import calendar
    year, month = int(year_month[:4]), int(year_month[5:7])
    last_day = calendar.monthrange(year, month)[1]
    start = f"{year_month}-01"
    end   = f"{year_month}-{last_day:02d}"

    spot_res = (sb.table("weekly_spot")
                  .select("investor_type,net_amount,week_date")
                  .gte("week_date", start)
                  .lte("week_date", end)
                  .execute())

    fut_res = (sb.table("weekly_combined")
                 .select("investor_type,futures_net_oku,week_date")
                 .gte("week_date", start)
                 .lte("week_date", end)
                 .execute())

    spot_by_inv    = defaultdict(list)
    futures_by_inv = defaultdict(list)

    for r in (spot_res.data or []):
        spot_by_inv[r["investor_type"]].append(r.get("net_amount") or 0)

    for r in (fut_res.data or []):
        futures_by_inv[r["investor_type"]].append(r.get("futures_net_oku") or 0)

    rows = []
    for inv in INVESTORS:
        s_vals = spot_by_inv.get(inv, [])
        f_vals = futures_by_inv.get(inv, [])
        s_sum  = sum(s_vals)
        f_sum  = sum(f_vals)
        rows.append({
            "year_month":      year_month,
            "investor_type":   inv,
            "spot_net_sum":    round(s_sum, 2),
            "futures_net_sum": round(f_sum, 2),
            "combined_net":    round(s_sum + f_sum, 2),
            "week_count":      max(len(s_vals), len(f_vals)),
        })

    logger.info(f"[月次] {year_month} の集計完了: {len(rows)}件")
    return rows


# ─────────────────────────────────────────
# 分析サマリー辞書（レポート生成用）
# ─────────────────────────────────────────
def build_analysis_context(week_date: date, db) -> dict:
    """
    レポート生成AIエージェントに渡す分析コンテキストを構築する
    """
    spot_rows    = db.fetch_week_spot(week_date)
    futures_rows = db.fetch_week_futures(week_date)
    # オプションは weekly_options テーブルから（存在しない過去週は空でOK）
    try:
        options_rows = db.fetch_week_options(week_date)
    except Exception:
        options_rows = []

    spot_map    = {r["investor_type"]: r for r in spot_rows}
    futures_map = defaultdict(lambda: {"net_amount_oku": 0, "long_lots": 0, "short_lots": 0})
    for r in futures_rows:
        futures_map[r["investor_type"]]["net_amount_oku"] += (r.get("net_amount_oku") or 0)
        futures_map[r["investor_type"]]["long_lots"]      += (r.get("long_lots") or 0)
        futures_map[r["investor_type"]]["short_lots"]     += (r.get("short_lots") or 0)

    investors_summary = []
    for inv in INVESTORS:
        s = spot_map.get(inv, {})
        f = futures_map[inv]

        spot_net  = s.get("net_amount", 0) or 0
        fut_net   = f["net_amount_oku"] or 0
        combined  = spot_net + fut_net
        twin_buy  = spot_net > 0 and fut_net > 0
        twin_sell = spot_net < 0 and fut_net < 0

        investors_summary.append({
            "key":          inv,
            "label":        INVESTOR_JP[inv],
            "spot_net":     round(spot_net, 2),
            "spot_buy":     round(s.get("buy_amount", 0) or 0, 2),
            "spot_sell":    round(s.get("sell_amount", 0) or 0, 2),
            "futures_net":  round(fut_net, 2),
            "combined_net": round(combined, 2),
            "is_twin_buy":  twin_buy,
            "is_twin_sell": twin_sell,
            "direction":    "買い越し" if combined > 0 else "売り越し",
        })

    # Zスコア付与（現物 + 先物）
    for inv_data in investors_summary:
        # 現物Zスコア
        hist = db.fetch_spot_history(inv_data["key"], 52)
        nets = [r["net_amount"] for r in hist if r.get("net_amount") is not None]
        inv_data["zscore_52w"] = calc_zscore(nets, 52) if nets else None
        inv_data["zscore_26w"] = calc_zscore(nets, 26) if nets else None
        inv_data["ma4w"]       = calc_ma(nets, 4) if nets else None
        inv_data["wow_change"] = round(nets[0] - nets[1], 2) if len(nets) >= 2 else None

        # 先物Zスコア（nikkei225_large + topix_large 合算）
        fut_hist = db.fetch_futures_history(inv_data["key"], weeks=52)
        fut_by_week = defaultdict(float)
        for r in fut_hist:
            fut_by_week[r["week_date"]] += (r.get("net_amount_oku") or 0)
        fut_nets = [v for _, v in sorted(fut_by_week.items(), reverse=True)]
        inv_data["futures_zscore_52w"] = calc_zscore(fut_nets, 52) if fut_nets else None
        inv_data["futures_zscore_26w"] = calc_zscore(fut_nets, 26) if fut_nets else None

    return {
        "week_date":  str(week_date),
        "investors":  investors_summary,
        "spot_rows":  spot_rows,
        "futures_rows": futures_rows,
        "options_rows": options_rows,
    }
