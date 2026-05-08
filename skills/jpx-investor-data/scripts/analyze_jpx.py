#!/usr/bin/env python3
"""
analyze_jpx.py
JPX投資家別売買データのパース・集計・分析を行う。

使用例:
  python scripts/analyze_jpx.py --spot /tmp/jpx_data/spot_2025.csv --futures /tmp/jpx_data/futures_2025.csv
  python scripts/analyze_jpx.py --spot /path/to/file.csv  # 現物のみ
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd

# 投資家区分の内部キー
INVESTOR_KEYS = ["foreign", "individual", "trust", "corporate", "dealer"]
INVESTOR_LABELS = {
    "foreign": "海外投資家",
    "individual": "個人投資家",
    "trust": "投信・信託銀行",
    "corporate": "事業法人",
    "dealer": "自己（証券会社）",
}

# カラム名のフレキシブルマッピング
SPOT_COLUMN_ALIASES = {
    "foreign_buy": ["海外投資家_買い付け", "外国人_買い", "外国人買い", "海外_買"],
    "foreign_sell": ["海外投資家_売り付け", "外国人_売り", "外国人売り", "海外_売"],
    "individual_buy": ["個人_買い付け", "個人投資家_買い", "個人_買"],
    "individual_sell": ["個人_売り付け", "個人投資家_売り", "個人_売"],
    "trust_buy": ["投信・信託銀行_買い付け", "信託銀行_買い", "投信_買い"],
    "trust_sell": ["投信・信託銀行_売り付け", "信託銀行_売り", "投信_売り"],
    "corporate_buy": ["事業法人_買い付け", "法人_買い", "事業法人_買"],
    "corporate_sell": ["事業法人_売り付け", "法人_売り", "事業法人_売"],
    "dealer_buy": ["自己_買い付け", "証券会社自己_買い", "自己_買"],
    "dealer_sell": ["自己_売り付け", "証券会社自己_売り", "自己_売"],
}


def try_read_csv(filepath: str) -> pd.DataFrame:
    """Shift-JIS/UTF-8を両方試してCSV読み込み"""
    for enc in ["shift_jis", "utf-8", "cp932", "utf-8-sig"]:
        try:
            df = pd.read_csv(filepath, encoding=enc, skiprows=0)
            # ヘッダー行を探す（最初の数行にデータが無いことがある）
            if df.shape[1] < 3:
                df = pd.read_csv(filepath, encoding=enc, skiprows=1)
            return df
        except Exception:
            continue
    raise ValueError(f"CSVの読み込みに失敗しました: {filepath}")


def flexible_column_map(df: pd.DataFrame, aliases: dict) -> dict:
    """カラム名を柔軟にマッピング。見つからないキーはNoneを返す"""
    mapping = {}
    cols_lower = {c.lower().replace(" ", "").replace("　", ""): c for c in df.columns}

    for key, candidates in aliases.items():
        found = None
        for candidate in candidates:
            normalized = candidate.lower().replace(" ", "").replace("　", "")
            if normalized in cols_lower:
                found = cols_lower[normalized]
                break
        mapping[key] = found

    return mapping


def calc_net(df: pd.DataFrame, col_map: dict, prefix: str) -> pd.Series:
    """買い越し・売り越しの差引を計算"""
    buy_col = col_map.get(f"{prefix}_buy")
    sell_col = col_map.get(f"{prefix}_sell")
    if buy_col and sell_col:
        return pd.to_numeric(df[buy_col], errors="coerce") - pd.to_numeric(df[sell_col], errors="coerce")
    return pd.Series([None] * len(df))


def analyze_spot(filepath: str) -> dict:
    """現物データの分析"""
    print(f"[現物] パース中: {filepath}")
    df = try_read_csv(filepath)
    col_map = flexible_column_map(df, SPOT_COLUMN_ALIASES)

    # 未マッピングのカラムを警告
    missing = [k for k, v in col_map.items() if v is None]
    if missing:
        print(f"[警告] 以下のカラムが見つかりません: {missing}")
        print(f"  実際のカラム: {list(df.columns)}")

    # 週付けカラムを探す
    date_col = next((c for c in df.columns if "週" in c or "date" in c.lower() or "日付" in c), None)
    if date_col:
        df["week_date"] = pd.to_datetime(df[date_col], errors="coerce")

    # 各投資家の差引計算
    results = []
    for key in INVESTOR_KEYS:
        net = calc_net(df, col_map, key)
        latest = net.dropna().iloc[-1] if not net.dropna().empty else None
        prev = net.dropna().iloc[-2] if len(net.dropna()) >= 2 else None
        week_diff = (latest - prev) if (latest is not None and prev is not None) else None

        results.append({
            "key": key,
            "label": INVESTOR_LABELS[key],
            "net_latest": latest,
            "net_prev": prev,
            "week_diff": week_diff,
            "net_series": net.tolist(),
        })

    return {
        "type": "spot",
        "filepath": filepath,
        "investors": results,
        "latest_date": df["week_date"].max().strftime("%Y-%m-%d") if "week_date" in df else "不明",
    }


def build_summary_table(analysis: dict) -> str:
    """Markdownテーブルを生成"""
    lines = []
    market_type = "現物（東証プライム）" if analysis["type"] == "spot" else "先物"

    lines.append(f"## {market_type}：投資家別買い越し・売り越し")
    lines.append("")
    lines.append("| 投資家区分 | 差引(億円) | 前週比 | 判定 |")
    lines.append("|-----------|----------|-------|------|")

    for inv in analysis["investors"]:
        net = inv["net_latest"]
        diff = inv["week_diff"]
        if net is None:
            lines.append(f"| {inv['label']} | - | - | - |")
            continue

        net_str = f"{'▲' if net > 0 else '▼'}{abs(net):,.0f}"
        diff_str = f"{'+' if diff >= 0 else ''}{diff:,.0f}" if diff is not None else "-"
        judge = "買い越し" if net > 0 else "売り越し"
        lines.append(f"| {inv['label']} | {net_str} | {diff_str} | {judge} |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="JPX投資家別データ分析")
    parser.add_argument("--spot", help="現物CSVのパス")
    parser.add_argument("--futures", help="先物CSVのパス")
    parser.add_argument("--output", default="/tmp/jpx_analysis.json", help="分析結果JSON出力先")
    args = parser.parse_args()

    analysis_results = {}

    if args.spot:
        analysis_results["spot"] = analyze_spot(args.spot)
        print(build_summary_table(analysis_results["spot"]))

    if args.futures:
        # 先物は構造が現物と異なるため別途対応（基本ロジックは同一）
        print("[先物] パース処理（spot準拠）")
        analysis_results["futures"] = analyze_spot(args.futures)
        analysis_results["futures"]["type"] = "futures"

    # JSON出力
    # シリアライズのためnet_seriesを省略
    for key in analysis_results:
        for inv in analysis_results[key]["investors"]:
            inv.pop("net_series", None)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(analysis_results, f, ensure_ascii=False, indent=2)

    print(f"\n[完了] 分析結果を保存: {args.output}")
    return analysis_results


if __name__ == "__main__":
    main()
