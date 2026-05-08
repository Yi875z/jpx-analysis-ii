#!/usr/bin/env python3
"""
fetch_jpx.py
JPXサイトから投資家別売買動向CSVを自動取得する。

使用例:
  python scripts/fetch_jpx.py --mode auto --type spot    # 現物のみ
  python scripts/fetch_jpx.py --mode auto --type futures # 先物のみ
  python scripts/fetch_jpx.py --mode auto --type all     # 両方（デフォルト）
  python scripts/fetch_jpx.py --mode manual --file path/to/file.csv
"""

import argparse
import os
import sys
import time
import requests
from pathlib import Path
from datetime import datetime, timedelta

# 出力先ディレクトリ
OUTPUT_DIR = Path("/tmp/jpx_data")
OUTPUT_DIR.mkdir(exist_ok=True)

# JPX CSVのURLパターン（年度ごとに変わる場合あり）
JPX_SPOT_BASE = "https://www.jpx.co.jp/markets/statistics-equities/investor-type/"
JPX_FUTURES_BASE = "https://www.jpx.co.jp/markets/statistics-derivatives/investor-type/"

def fetch_spot_data(year: int = None) -> Path:
    """現物（東証プライム）の投資家別売買データを取得"""
    if year is None:
        year = datetime.now().year

    # JPXの実際のCSVリンクを探すためにHTMLをパース
    index_url = f"{JPX_SPOT_BASE}00-archives-07.html"
    print(f"[現物] インデックスページ取得: {index_url}")

    try:
        resp = requests.get(index_url, timeout=30,
                           headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[エラー] 現物データ取得失敗: {e}")
        print("手動でJPXサイトからCSVをダウンロードしてください。")
        print(f"URL: {index_url}")
        return None

    # CSVリンクを抽出（簡易パース）
    from html.parser import HTMLParser

    class LinkParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.csv_links = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                attrs_dict = dict(attrs)
                href = attrs_dict.get("href", "")
                if ".csv" in href.lower() or ".xls" in href.lower():
                    self.csv_links.append(href)

    parser = LinkParser()
    parser.feed(resp.text)

    if not parser.csv_links:
        print("[警告] CSVリンクが見つかりません。JPXのサイト構造が変わった可能性があります。")
        print("手動ダウンロードを試みてください。")
        return None

    # 最新リンクを取得
    latest_link = parser.csv_links[0]
    if not latest_link.startswith("http"):
        latest_link = "https://www.jpx.co.jp" + latest_link

    print(f"[現物] CSVダウンロード: {latest_link}")
    csv_resp = requests.get(latest_link, timeout=30,
                           headers={"User-Agent": "Mozilla/5.0"})
    csv_resp.raise_for_status()

    # Shift-JIS対応
    output_path = OUTPUT_DIR / f"spot_{year}.csv"
    with open(output_path, "wb") as f:
        f.write(csv_resp.content)

    print(f"[現物] 保存完了: {output_path}")
    return output_path


def fetch_futures_data(year: int = None) -> Path:
    """先物の投資家別売買データを取得"""
    if year is None:
        year = datetime.now().year

    index_url = f"{JPX_FUTURES_BASE}index.html"
    print(f"[先物] インデックスページ取得: {index_url}")

    try:
        resp = requests.get(index_url, timeout=30,
                           headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[エラー] 先物データ取得失敗: {e}")
        print("手動でJPXサイトからCSVをダウンロードしてください。")
        print(f"URL: {index_url}")
        return None

    # 同様にリンク抽出
    from html.parser import HTMLParser

    class LinkParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.csv_links = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                attrs_dict = dict(attrs)
                href = attrs_dict.get("href", "")
                if ".csv" in href.lower() or ".xls" in href.lower():
                    self.csv_links.append(href)

    parser = LinkParser()
    parser.feed(resp.text)

    if not parser.csv_links:
        print("[警告] 先物CSVリンクが見つかりません。")
        return None

    latest_link = parser.csv_links[0]
    if not latest_link.startswith("http"):
        latest_link = "https://www.jpx.co.jp" + latest_link

    print(f"[先物] CSVダウンロード: {latest_link}")
    csv_resp = requests.get(latest_link, timeout=30,
                           headers={"User-Agent": "Mozilla/5.0"})
    csv_resp.raise_for_status()

    output_path = OUTPUT_DIR / f"futures_{year}.csv"
    with open(output_path, "wb") as f:
        f.write(csv_resp.content)

    print(f"[先物] 保存完了: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="JPX投資家別売買データ取得")
    parser.add_argument("--mode", choices=["auto", "manual"], default="auto")
    parser.add_argument("--type", choices=["spot", "futures", "all"], default="all")
    parser.add_argument("--file", help="手動モード時のファイルパス")
    parser.add_argument("--year", type=int, default=None)
    args = parser.parse_args()

    results = {}

    if args.mode == "manual":
        if not args.file:
            print("[エラー] 手動モード時は --file でファイルパスを指定してください")
            sys.exit(1)
        print(f"[手動] ファイル使用: {args.file}")
        results["manual"] = Path(args.file)
    else:
        if args.type in ("spot", "all"):
            results["spot"] = fetch_spot_data(args.year)
            time.sleep(1)  # JPXへの負荷軽減

        if args.type in ("futures", "all"):
            results["futures"] = fetch_futures_data(args.year)

    print("\n=== 取得結果 ===")
    for key, path in results.items():
        status = f"✅ {path}" if path else "❌ 取得失敗"
        print(f"{key}: {status}")

    return results


if __name__ == "__main__":
    main()
