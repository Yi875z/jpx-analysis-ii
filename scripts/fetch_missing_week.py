"""
scripts/fetch_missing_week.py
=============================
JPXページに掲載されている特定週の現物XLS・先物CSVをダウンロードして
DBに投入する。欠落週の追加取得用。

使い方:
  python scripts/fetch_missing_week.py --week-end 2026-05-01
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

import main as jpx_main  # run_weekly を再利用
from scripts.jpx_week_resolver import (
    HEADERS,
    JPX_FUTURES_INDEX,
    JPX_SPOT_INDEX,
    _decode,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


_STOCK_VAL_HREF_RE = re.compile(
    r'href="([^"]+stock_val_1_(\d{6})\.xls)"', re.IGNORECASE
)
_FUTURES_HREF_RE = re.compile(
    r'href="([^"]+Tousi_DV_W_(\d{8})_(\d{8})\.csv)"', re.IGNORECASE
)


def _fetch_jpx_pages() -> tuple[str, str]:
    spot = requests.get(JPX_SPOT_INDEX, headers=HEADERS, timeout=30)
    fut  = requests.get(JPX_FUTURES_INDEX, headers=HEADERS, timeout=30)
    return _decode(spot), _decode(fut)


def _full_url(href: str) -> str:
    if href.startswith("http"):
        return href
    return "https://www.jpx.co.jp" + href


def _find_spot_url(spot_html: str, week_end: date) -> str | None:
    """対象週末日に対応する stock_val URL を探す。
    JPX_SPOT_INDEX を解析して、jpx_week_resolver と同じ手法で
    {filename: week_end} を作って逆引きする。
    """
    from scripts.jpx_week_resolver import _STOCK_VAL_RE, _parse_pairs
    mapping = _parse_pairs(spot_html, _STOCK_VAL_RE)
    target_stem = None
    for stem, wi in mapping.items():
        if wi.week_end == week_end:
            target_stem = stem
            break
    if not target_stem:
        return None
    # HTML 内からその stem を含むhrefを探す
    pattern = re.compile(rf'href="([^"]+{re.escape(target_stem)}\.xls)"', re.IGNORECASE)
    m = pattern.search(spot_html)
    return _full_url(m.group(1)) if m else None


def _find_futures_url(fut_html: str, week_start: date, week_end: date) -> str | None:
    """先物CSV URLを探す。Tousi_DV_W_YYYYMMDD_YYYYMMDD.csv のパターン"""
    pattern = re.compile(
        rf'href="([^"]+Tousi_DV_W_{week_start.strftime("%Y%m%d")}_{week_end.strftime("%Y%m%d")}\.csv)"',
        re.IGNORECASE,
    )
    m = pattern.search(fut_html)
    return _full_url(m.group(1)) if m else None


def _download(url: str, suffix: str) -> Path:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(r.content)
    return Path(tmp)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--week-end", required=True, help="週末日（金）例: 2026-05-01")
    p.add_argument("--no-report", action="store_true",
                   help="DB投入のみ。AIレポート生成をスキップ")
    args = p.parse_args()

    week_end = date.fromisoformat(args.week_end)
    week_start = week_end.fromordinal(week_end.toordinal() - 4)

    print(f"=== 欠落週取得: {week_start} 〜 {week_end} ===\n")

    spot_html, fut_html = _fetch_jpx_pages()

    spot_url = _find_spot_url(spot_html, week_end)
    fut_url  = _find_futures_url(fut_html, week_start, week_end)

    print(f"現物 URL: {spot_url}")
    print(f"先物 URL: {fut_url}")

    if not spot_url and not fut_url:
        print("対応するファイルが JPX ページに見つかりませんでした。")
        return

    spot_path = _download(spot_url, ".xls") if spot_url else None
    fut_path  = _download(fut_url,  ".csv") if fut_url  else None

    print()
    if args.no_report:
        # DB投入のみ
        from scripts import fetch_jpx as fj
        from db import supabase_client as db
        result = fj.parse_manual(
            spot_path=str(spot_path) if spot_path else None,
            futures_path=str(fut_path) if fut_path else None,
            week_date=week_end,
        )
        n_spot = db.upsert_spot(result.get("spot", []))
        n_fut  = db.upsert_futures(result.get("futures", []))
        print(f"[DB] 現物={n_spot}件 / 先物={n_fut}件 upsert")
        # 合算・統計も
        from scripts import analyze_jpx as az
        combined = az.build_combined(result.get("spot", []), result.get("futures", []), week_end)
        db.upsert_combined(combined)
        stats = az.build_stats(week_end, db)
        db.upsert_stats(stats)
        print("[DB] combined / stats も更新完了")
    else:
        # フル実行（レポート生成含む）
        jpx_main.run_weekly(
            week_date=week_end,
            spot_path=str(spot_path) if spot_path else None,
            futures_path=str(fut_path) if fut_path else None,
        )

    # 後始末
    for p_ in (spot_path, fut_path):
        if p_:
            try:
                p_.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    main()
