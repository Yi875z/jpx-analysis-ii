"""
scripts/fetch_jpx.py
JPXサイトから投資家別売買動向CSVを取得してSupabaseに蓄積する
"""

import io
import os
import time
import logging
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
import requests
import pandas as pd

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# JPX URL
# ─────────────────────────────────────────
JPX_SPOT_INDEX    = "https://www.jpx.co.jp/markets/statistics-equities/investor-type/index.html"
JPX_FUTURES_INDEX = "https://www.jpx.co.jp/markets/statistics-derivatives/sector/index.html"
JPX_BASE          = "https://www.jpx.co.jp"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# 投資家区分マッピング（JPX表記 → 内部キー）
INVESTOR_MAP = {
    "海外投資家": "foreign",
    "外国人": "foreign",
    "個人": "individual",
    "個人投資家": "individual",
    "投信": "trust",
    "信託銀行": "trust",
    "投信・信託銀行": "trust",
    "事業法人": "corporate",
    "自己": "dealer",
    "自己（証券）": "dealer",
}

INVESTOR_ORDER = ["foreign", "individual", "trust", "corporate", "dealer"]


# ─────────────────────────────────────────
# HTMLからCSVリンクを抽出
# ─────────────────────────────────────────
class CsvLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            d = dict(attrs)
            href = d.get("href", "")
            if ".csv" in href.lower() or ".xls" in href.lower():
                self.links.append(href)


def _get_csv_links(index_url: str) -> list[str]:
    resp = requests.get(index_url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    parser = CsvLinkParser()
    parser.feed(resp.text)
    links = []
    for href in parser.links:
        full = href if href.startswith("http") else JPX_BASE + href
        # 現物ページでは出来高(vol)を除外し金額(val)のみ対象
        if "stock_vol" in full:
            continue
        links.append(full)
    return links


def _download_to_tempfile(url: str) -> Path:
    """URLをダウンロードして一時ファイルに保存し、Pathを返す"""
    import tempfile
    suffix = Path(url.split("?")[0]).suffix or ".tmp"
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(resp.content)
    return Path(tmp_path)


def _download_csv(url: str) -> bytes:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.content


# ─────────────────────────────────────────
# CSV → DataFrame
# ─────────────────────────────────────────
def _read_csv_flex(content: bytes) -> pd.DataFrame:
    """エンコーディングを自動判定してCSVを読む"""
    for enc in ["shift_jis", "cp932", "utf-8-sig", "utf-8"]:
        try:
            df = pd.read_csv(io.BytesIO(content), encoding=enc)
            if df.shape[1] >= 3:
                return df
            # ヘッダー行がずれている場合
            df = pd.read_csv(io.BytesIO(content), encoding=enc, skiprows=1)
            if df.shape[1] >= 3:
                return df
        except Exception:
            continue
    raise ValueError("CSVの読み込みに失敗しました（エンコード不明）")


def _normalize_col(col: str) -> str:
    return col.strip().replace("　", "").replace(" ", "").lower()


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    norm_map = {_normalize_col(c): c for c in df.columns}
    for cand in candidates:
        key = _normalize_col(cand)
        if key in norm_map:
            return norm_map[key]
    return None


# ─────────────────────────────────────────
# 現物データのパース
# ─────────────────────────────────────────
def parse_spot(content: bytes, week_date: date, source_url: str) -> list[dict]:
    df = _read_csv_flex(content)

    # 週付け列を推定
    date_col = _find_col(df, ["週", "対象週", "日付", "date", "week"])
    if date_col:
        df["week_date_raw"] = pd.to_datetime(df[date_col], errors="coerce")
    else:
        df["week_date_raw"] = pd.NaT

    # 投資家列を探す
    investor_col = _find_col(df, ["投資部門", "投資家", "区分", "部門"])
    buy_col  = _find_col(df, ["買付金額", "買い付け", "買付", "buy"])
    sell_col = _find_col(df, ["売付金額", "売り付け", "売付", "sell"])

    rows = []
    for _, row in df.iterrows():
        investor_raw = str(row.get(investor_col, "")).strip() if investor_col else ""
        investor_key = None
        for k, v in INVESTOR_MAP.items():
            if k in investor_raw:
                investor_key = v
                break
        if investor_key is None:
            continue

        try:
            buy  = float(str(row[buy_col]).replace(",", "")) if buy_col else None
            sell = float(str(row[sell_col]).replace(",", "")) if sell_col else None
        except (ValueError, TypeError):
            continue

        net = (buy - sell) if (buy is not None and sell is not None) else None

        rows.append({
            "week_date":     str(week_date),
            "investor_type": investor_key,
            "buy_amount":    round(buy / 1e8, 2) if buy else None,   # 千円→億円
            "sell_amount":   round(sell / 1e8, 2) if sell else None,
            "net_amount":    round(net / 1e8, 2) if net else None,
            "market":        "prime",
            "source_url":    source_url,
        })

    logger.info(f"[現物] パース完了: {len(rows)}件 / week={week_date}")
    return rows


# ─────────────────────────────────────────
# 先物データのパース
# ─────────────────────────────────────────
def parse_futures(content: bytes, week_date: date, source_url: str,
                  index_close: float = 0.0) -> list[dict]:
    df = _read_csv_flex(content)

    investor_col  = _find_col(df, ["投資部門", "投資家", "区分"])
    futures_col   = _find_col(df, ["商品", "先物種別", "product"])
    long_col      = _find_col(df, ["買建", "買い建て", "long"])
    short_col     = _find_col(df, ["売建", "売り建て", "short"])

    FUTURES_MAP = {
        "日経225": "nikkei225_large",
        "日経225ラージ": "nikkei225_large",
        "日経225mini": "nikkei225_mini",
        "TOPIXラージ": "topix_large",
        "TOPIX": "topix_large",
        "TOPIXmini": "topix_mini",
    }
    MULTIPLIER = {
        "nikkei225_large": 1000,
        "nikkei225_mini": 100,
        "topix_large": 10000,
        "topix_mini": 1000,
    }

    rows = []
    for _, row in df.iterrows():
        investor_raw = str(row.get(investor_col, "")).strip() if investor_col else ""
        investor_key = None
        for k, v in INVESTOR_MAP.items():
            if k in investor_raw:
                investor_key = v
                break
        if investor_key is None:
            continue

        futures_raw = str(row.get(futures_col, "")).strip() if futures_col else "nikkei225_large"
        futures_key = "nikkei225_large"
        for k, v in FUTURES_MAP.items():
            if k in futures_raw:
                futures_key = v
                break

        try:
            long_v  = int(float(str(row[long_col]).replace(",", "")))  if long_col  else 0
            short_v = int(float(str(row[short_col]).replace(",", ""))) if short_col else 0
        except (ValueError, TypeError):
            continue

        net_lots = long_v - short_v

        # 億円換算
        net_oku = None
        if index_close > 0:
            mult = MULTIPLIER.get(futures_key, 1000)
            net_oku = round(net_lots * index_close * mult / 1e8, 2)

        rows.append({
            "week_date":     str(week_date),
            "investor_type": investor_key,
            "futures_type":  futures_key,
            "long_lots":     long_v,
            "short_lots":    short_v,
            "net_lots":      net_lots,
            "index_close":   index_close,
            "net_amount_oku": net_oku,
            "source_url":    source_url,
        })

    logger.info(f"[先物] パース完了: {len(rows)}件 / week={week_date}")
    return rows


# ─────────────────────────────────────────
# メイン取得関数
# ─────────────────────────────────────────
def fetch_all(week_date: date, index_close: float = 0.0) -> dict:
    """JPXから現物・先物を自動取得してパース結果を返す"""
    result = {"spot": [], "futures": [], "errors": []}

    # ── 現物（XLS形式） ──────────────────────────────────────────────────
    try:
        links = _get_csv_links(JPX_SPOT_INDEX)
        # XLSリンクを優先、なければCSVリンク
        xls_links = [l for l in links if l.lower().endswith(".xls") or l.lower().endswith(".xlsx")]
        target = xls_links[0] if xls_links else (links[0] if links else None)
        if target is None:
            result["errors"].append("現物ファイルリンクが見つかりません")
        else:
            logger.info(f"[自動取得] 現物: {target}")
            tmp = _download_to_tempfile(target)
            try:
                ext = tmp.suffix.lower()
                if ext in (".xls", ".xlsx"):
                    from .parse_spot_xls import parse_spot_xls
                    rows = parse_spot_xls(str(tmp), str(week_date))
                    for row in rows:
                        row.setdefault("source_url", target)
                    result["spot"] = rows
                else:
                    content = tmp.read_bytes()
                    result["spot"] = parse_spot(content, week_date, target)
            finally:
                tmp.unlink(missing_ok=True)
    except Exception as e:
        result["errors"].append(f"現物取得エラー: {e}")

    time.sleep(2)  # JPXへの負荷軽減

    # ── 先物（ヘッダーなしCSV形式） ──────────────────────────────────────
    try:
        links = _get_csv_links(JPX_FUTURES_INDEX)
        csv_links = [l for l in links if l.lower().endswith(".csv")]
        target = csv_links[0] if csv_links else (links[0] if links else None)
        if target is None:
            result["errors"].append("先物CSVリンクが見つかりません")
        else:
            logger.info(f"[自動取得] 先物: {target}")
            tmp = _download_to_tempfile(target)
            try:
                ext = tmp.suffix.lower()
                if ext == ".csv":
                    from .parse_futures_csv import parse_futures_csv
                    result["futures"] = parse_futures_csv(str(tmp), str(week_date))
                else:
                    content = tmp.read_bytes()
                    result["futures"] = parse_futures(content, week_date, target, index_close)
            finally:
                tmp.unlink(missing_ok=True)
    except Exception as e:
        result["errors"].append(f"先物取得エラー: {e}")

    return result


# ─────────────────────────────────────────
# 手動CSVモード（ファイルアップロード対応）
# ─────────────────────────────────────────
def parse_manual(spot_path: str = None, futures_path: str = None,
                 week_date: date = None, index_close: float = 0.0) -> dict:
    """ユーザーが手動でDLしたCSVをパース"""
    if week_date is None:
        week_date = date.today()

    result = {"spot": [], "futures": [], "errors": []}

    if spot_path:
        try:
            ext = Path(spot_path).suffix.lower()
            if ext in (".xls", ".xlsx"):
                # JPX現物はXLS形式 → 専用パーサーを使用
                from .parse_spot_xls import parse_spot_xls
                rows = parse_spot_xls(spot_path, str(week_date))
                for row in rows:
                    row.setdefault("source_url", f"manual:{spot_path}")
                result["spot"] = rows
            else:
                content = Path(spot_path).read_bytes()
                result["spot"] = parse_spot(content, week_date, f"manual:{spot_path}")
        except Exception as e:
            result["errors"].append(f"現物手動パースエラー: {e}")

    if futures_path:
        try:
            ext = Path(futures_path).suffix.lower()
            if ext == ".csv":
                # JPX先物CSVはヘッダーなし列インデックス形式 → 修正済みパーサーを使用
                from .parse_futures_csv import parse_futures_csv
                result["futures"] = parse_futures_csv(futures_path, str(week_date))
            else:
                content = Path(futures_path).read_bytes()
                result["futures"] = parse_futures(content, week_date, f"manual:{futures_path}", index_close)
        except Exception as e:
            result["errors"].append(f"先物手動パースエラー: {e}")

    return result
