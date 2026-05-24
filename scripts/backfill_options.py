"""
scripts/backfill_options.py
===========================
JPX のインデックスページから現在公開されている週次 CSV を順次取得し、
日経225オプション（標準・ミニ）の投資家別売買データを weekly_options テーブルに投入する。

- 先物データと同じCSV（Tousi_DV_W_*.csv）から抽出
- 既存レコードは upsert（UNIQUE(week_date, investor_type, option_type)）で安全に更新
- week_date は JPX 記載の対象期間末日（金曜）を採用

使い方:
  python scripts/backfill_options.py                # 公開中の全週を投入
  python scripts/backfill_options.py --dry-run       # ダウンロードはしてDB投入だけスキップ
"""

from __future__ import annotations

import argparse
import logging
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

from db import supabase_client as db
from scripts.jpx_week_resolver import HEADERS, JPX_FUTURES_INDEX, _decode
from scripts.parse_options_csv import parse_options_csv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


_CSV_HREF_RE = re.compile(
    r'href="([^"]+Tousi_DV_W_(\d{8})_(\d{8})\.csv)"',
    re.IGNORECASE,
)


def fetch_csv_list() -> list[tuple[str, date, date]]:
    """JPX 先物インデックスから (URL, 週初日, 週末日) のリストを返す"""
    r = requests.get(JPX_FUTURES_INDEX, headers=HEADERS, timeout=30)
    r.raise_for_status()
    html = _decode(r)
    out: list[tuple[str, date, date]] = []
    seen: set[str] = set()
    for m in _CSV_HREF_RE.finditer(html):
        href = m.group(1)
        if href in seen:
            continue
        seen.add(href)
        ws_str = m.group(2)
        we_str = m.group(3)
        ws = date(int(ws_str[:4]), int(ws_str[4:6]), int(ws_str[6:8]))
        we = date(int(we_str[:4]), int(we_str[4:6]), int(we_str[6:8]))
        full = href if href.startswith("http") else "https://www.jpx.co.jp" + href
        out.append((full, ws, we))
    return sorted(out, key=lambda x: x[2])  # 古い順


def download_csv(url: str) -> Path:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    import os
    fd, tmp = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "wb") as f:
        f.write(r.content)
    return Path(tmp)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="DBへの書き込みをスキップ")
    args = p.parse_args()

    print("=== JPX オプションデータ バックフィル ===\n")

    csv_list = fetch_csv_list()
    print(f"[1/2] JPX公開中の先物CSV数: {len(csv_list)} 週")
    for url, ws, we in csv_list:
        print(f"  {ws} 〜 {we}  ({url.rsplit('/', 1)[-1]})")
    print()

    if not csv_list:
        print("CSVが見つかりませんでした。終了。")
        return

    print(f"[2/2] {'DRY-RUN' if args.dry_run else '投入'} 開始\n")
    total_rows = 0
    for url, ws, we in csv_list:
        wd_str = we.isoformat()
        print(f"--- {ws} 〜 {we} ({we}) ---")
        try:
            tmp = download_csv(url)
        except Exception as e:
            print(f"  [error] DL失敗: {e}")
            continue
        try:
            rows = parse_options_csv(str(tmp), wd_str, source_url=url)
        except Exception as e:
            print(f"  [error] パース失敗: {e}")
            tmp.unlink(missing_ok=True)
            continue
        tmp.unlink(missing_ok=True)

        # サマリ：海外投資家の各 option_type
        for r in rows:
            if r["investor_type"] == "foreign":
                sign = "+" if r["net_lots"] >= 0 else ""
                print(
                    f"  foreign / {r['option_type']:22s}: "
                    f"net={sign}{r['net_lots']:+,}枚 / {r['net_amount_oku']:+8.1f}億"
                )

        if not args.dry_run:
            n = db.upsert_options(rows)
            print(f"  [DB] upsert {n} 件")
        total_rows += len(rows)

    print()
    print(f"=== 完了: {total_rows} レコード処理 ===")


if __name__ == "__main__":
    main()
