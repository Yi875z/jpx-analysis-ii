"""
scripts/backfill_jpx.py
JPXアーカイブから過去データを一括取得してSupabaseに投入するスクリプト。

使い方:
  # 2025年4月以降を全件バックフィル
  python scripts/backfill_jpx.py

  # 開始日を指定（デフォルト: 2025-04-01）
  python scripts/backfill_jpx.py --from 2025-04-01

  # ドライランで何件処理されるか確認
  python scripts/backfill_jpx.py --dry-run
"""

import argparse
import os
import re
import sys
import time
import logging
import tempfile
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

import requests

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

JPX_BASE = "https://www.jpx.co.jp"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# 現物アーカイブ（年度別）
SPOT_PAGES = [
    "https://www.jpx.co.jp/markets/statistics-equities/investor-type/00-00-archives-01.html",  # 2025
    "https://www.jpx.co.jp/markets/statistics-equities/investor-type/00-00-archives-00.html",  # 2026
    "https://www.jpx.co.jp/markets/statistics-equities/investor-type/index.html",               # 2026最新
]

# 先物アーカイブ（年度別）
FUTURES_PAGES = [
    "https://www.jpx.co.jp/markets/statistics-derivatives/sector/00-archives-01.html",  # 2025
    "https://www.jpx.co.jp/markets/statistics-derivatives/sector/00-archives-00.html",  # 2026
    "https://www.jpx.co.jp/markets/statistics-derivatives/sector/index.html",           # 2026最新
]


# ─────────────────────────────────────────
# リンク収集
# ─────────────────────────────────────────
class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            d = dict(attrs)
            href = d.get("href", "")
            if ".csv" in href.lower() or ".xls" in href.lower():
                self.links.append(href)


def _collect_links(pages: list[str]) -> list[str]:
    all_links = []
    for url in pages:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            p = LinkParser()
            p.feed(r.text)
            for href in p.links:
                full = href if href.startswith("http") else JPX_BASE + href
                all_links.append(full)
            time.sleep(1)
        except Exception as e:
            logger.warning(f"ページ取得失敗: {url} → {e}")
    return all_links


# ─────────────────────────────────────────
# ファイル名から日付情報を解析
# ─────────────────────────────────────────
def _parse_spot_key(url: str):
    """
    stock_val_1_YYMMWW.xls → (year, month, week_num)
    例: stock_val_1_250401.xls → (2025, 4, 1)
    """
    m = re.search(r"stock_val_1_(\d{2})(\d{2})(\d{2})\.xls", url, re.IGNORECASE)
    if not m:
        return None
    yy, mm, ww = int(m.group(1)), int(m.group(2)), int(m.group(3))
    year = 2000 + yy
    return (year, mm, ww)


def _parse_futures_info(url: str):
    """
    Tousi_DV_W_YYYYMM_N_MMDD_MMDD.csv → (year, month, week_num, end_date)
    例: Tousi_DV_W_202504_2_0407_0411.csv → (2025, 4, 2, date(2025,4,11))
    """
    m = re.search(r"Tousi_DV_W_(\d{4})(\d{2})_(\d+)_(\d{4})_(\d{4})\.csv", url, re.IGNORECASE)
    if not m:
        return None
    year, month, week_num = int(m.group(1)), int(m.group(2)), int(m.group(3))
    end_mmdd = m.group(5)
    end_month = int(end_mmdd[:2])
    end_day = int(end_mmdd[2:])
    # 月またぎ対応（例: 0331_0404 → end は翌月）
    end_year = year if end_month >= month else year + 1
    try:
        end_date = date(end_year, end_month, end_day)
    except ValueError:
        return None
    return (year, month, week_num, end_date)


# ─────────────────────────────────────────
# 処理済み週を確認
# ─────────────────────────────────────────
def _get_done_dates() -> set[date]:
    """outputs/reports/ にあるレポートから処理済みの週付けを収集"""
    report_dir = Path(__file__).resolve().parent.parent / "outputs" / "reports"
    done = set()
    for f in report_dir.glob("jpx_investor_*.md"):
        m = re.search(r"jpx_investor_(\d{8})\.md", f.name)
        if m:
            try:
                done.add(datetime.strptime(m.group(1), "%Y%m%d").date())
            except ValueError:
                pass
    return done


# ─────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_date", default="2025-04-01",
                        help="取得開始日 YYYY-MM-DD（デフォルト: 2025-04-01）")
    parser.add_argument("--dry-run", action="store_true",
                        help="ダウンロード・保存せず処理対象を表示のみ")
    args = parser.parse_args()

    from_date = datetime.strptime(args.from_date, "%Y-%m-%d").date()
    logger.info(f"バックフィル開始: {from_date} 以降")

    # ── 全リンク収集 ──────────────────────────────────────────────────────
    logger.info("現物リンクを収集中...")
    spot_links = _collect_links(SPOT_PAGES)
    spot_links = [l for l in spot_links if "stock_val_" in l and "stock_vol_" not in l]

    logger.info("先物リンクを収集中...")
    futures_links = _collect_links(FUTURES_PAGES)
    futures_links = [l for l in futures_links
                     if re.search(r"Tousi_DV_W_\d{6}_\d+_\d{4}_\d{4}\.csv", l, re.IGNORECASE)]

    logger.info(f"現物: {len(spot_links)}件, 先物: {len(futures_links)}件")

    # ── 先物を基準にペアを作成 ─────────────────────────────────────────────
    # 先物CSVの (year, month, week_num) → URL のマップ
    futures_map = {}
    for url in futures_links:
        info = _parse_futures_info(url)
        if info:
            year, month, week_num, end_date = info
            futures_map[(year, month, week_num)] = (url, end_date)

    # 現物XLSの (year, month, week_num) → URL のマップ
    spot_map = {}
    for url in spot_links:
        key = _parse_spot_key(url)
        if key:
            spot_map[key] = url

    # ── ペアリング ─────────────────────────────────────────────────────────
    pairs = []
    for key, (futures_url, end_date) in futures_map.items():
        if end_date < from_date:
            continue
        spot_url = spot_map.get(key)
        if spot_url is None:
            logger.warning(f"現物ファイルが見つかりません: {key} (先物: {futures_url.split('/')[-1]})")
            continue
        pairs.append((end_date, spot_url, futures_url))

    pairs.sort(key=lambda x: x[0])  # 日付昇順

    # ── 処理済みスキップ ───────────────────────────────────────────────────
    done_dates = _get_done_dates()
    pending = [(d, s, f) for d, s, f in pairs if d not in done_dates]

    logger.info(f"対象: {len(pairs)}週, スキップ済み: {len(pairs)-len(pending)}週, 処理予定: {len(pending)}週")

    if args.dry_run:
        print("\n=== ドライラン結果 ===")
        for end_date, spot_url, futures_url in pending:
            print(f"  {end_date}  {spot_url.split('/')[-1]}  /  {futures_url.split('/')[-1]}")
        return

    if not pending:
        logger.info("処理対象なし（全て取得済み）")
        return

    # ── 実際の処理 ────────────────────────────────────────────────────────
    import subprocess
    success_count = 0
    fail_count = 0

    for i, (end_date, spot_url, futures_url) in enumerate(pending, 1):
        logger.info(f"[{i}/{len(pending)}] {end_date}: {spot_url.split('/')[-1]} + {futures_url.split('/')[-1]}")

        # ダウンロード
        try:
            spot_r = requests.get(spot_url, headers=HEADERS, timeout=60)
            spot_r.raise_for_status()
            futures_r = requests.get(futures_url, headers=HEADERS, timeout=60)
            futures_r.raise_for_status()
        except Exception as e:
            logger.error(f"ダウンロード失敗: {e}")
            fail_count += 1
            continue

        # 一時ファイルに保存
        with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tf_spot:
            tf_spot.write(spot_r.content)
            spot_tmp = tf_spot.name
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf_fut:
            tf_fut.write(futures_r.content)
            futures_tmp = tf_fut.name

        # main.py を呼び出してDB保存+レポート生成
        try:
            root = Path(__file__).resolve().parent.parent
            result = subprocess.run(
                [sys.executable, "main.py",
                 "--spot", spot_tmp,
                 "--futures", futures_tmp,
                 "--date", str(end_date)],
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )
            if result.returncode == 0:
                logger.info(f"  [OK] {end_date}")
                success_count += 1
            else:
                logger.error(f"  [失敗] {end_date}\n{result.stderr[-500:]}")
                fail_count += 1
        except Exception as e:
            logger.error(f"  [例外] {end_date}: {e}")
            fail_count += 1
        finally:
            os.unlink(spot_tmp)
            os.unlink(futures_tmp)

        time.sleep(3)  # JPXへの負荷軽減

    logger.info(f"\n=== 完了: 成功 {success_count}件 / 失敗 {fail_count}件 ===")


if __name__ == "__main__":
    main()
