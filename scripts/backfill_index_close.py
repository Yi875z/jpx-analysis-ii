"""
scripts/backfill_index_close.py
================================
weekly_futures の index_close が 0.0 / NULL のまま保存されている過去週に、
Yahoo Finance から取得した実際の週末日経225終値を埋める一回限りのバックフィル。

背景: 2026-06-07 の修正以前は run_weekly が index_close を永続化しておらず、
0.0 のまま DB に保存されていた（net_amount_oku 自体は取得時の指数値で
正しく計算済みのため、本スクリプトは index_close 列のみを更新する）。

使い方:
  python scripts/backfill_index_close.py            # 実行
  python scripts/backfill_index_close.py --dry-run  # 更新せずに対象と取得値を表示
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

from db import supabase_client as db
from scripts import fetch_index

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def find_target_weeks() -> list[str]:
    """index_close が 0 または NULL の week_date 一覧（昇順・重複なし）"""
    sb = db.get_client()
    weeks: set[str] = set()
    res = (sb.table("weekly_futures").select("week_date")
           .eq("index_close", 0.0).execute())
    weeks.update(r["week_date"] for r in res.data or [])
    res = (sb.table("weekly_futures").select("week_date")
           .is_("index_close", "null").execute())
    weeks.update(r["week_date"] for r in res.data or [])
    return sorted(weeks)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    targets = find_target_weeks()
    logger.info(f"対象週: {len(targets)}件")
    if not targets:
        print("[OK] index_close が未設定の週はありません")
        return

    sb = db.get_client()
    n_updated = 0
    n_failed = 0
    for wd in targets:
        hit = fetch_index.get_close_on_or_before(date.fromisoformat(wd), "nikkei225")
        if not hit:
            logger.warning(f"{wd}: 終値を取得できず → スキップ")
            n_failed += 1
            continue
        close_date, close = hit
        logger.info(f"{wd}: {close_date} 終値 {close:,.2f}円")
        if not args.dry_run:
            (sb.table("weekly_futures").update({"index_close": close})
             .eq("week_date", wd).eq("index_close", 0.0).execute())
            (sb.table("weekly_futures").update({"index_close": close})
             .eq("week_date", wd).is_("index_close", "null").execute())
        n_updated += 1
        time.sleep(0.4)  # Yahoo API への連続アクセスを抑制

    mode = "(dry-run) " if args.dry_run else ""
    print(f"\n[OK] {mode}バックフィル完了: 更新 {n_updated}週 / 取得失敗 {n_failed}週")


if __name__ == "__main__":
    main()
