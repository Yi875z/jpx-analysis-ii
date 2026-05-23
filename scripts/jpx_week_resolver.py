"""
scripts/jpx_week_resolver.py
============================
JPXインデックスページから「ファイル名 → 対象週末日」のマッピングを取得する。

JPXのファイル名規則は単純な「月内第N金曜」では再現できないため、
HTMLに記載されている期間表記（YYYY年MM月第N週(MM月DD日〜MM月DD日)）を
正規表現で直接抽出して対応関係を作る。

提供API:
  resolve_from_jpx() -> {filename_stem: WeekInfo}
  resolve_from_url(source_url) -> WeekInfo | None
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

import requests

logger = logging.getLogger(__name__)

JPX_SPOT_INDEX    = "https://www.jpx.co.jp/markets/statistics-equities/investor-type/index.html"
JPX_FUTURES_INDEX = "https://www.jpx.co.jp/markets/statistics-derivatives/sector/index.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# JPXページに書かれている期間表記
_WEEK_RE = re.compile(
    r"(\d{4})年(\d{1,2})月第(\d+)週\((\d{1,2})月(\d{1,2})日.{1,5}(\d{1,2})月(\d{1,2})日\)"
)

# ファイル名 stem 抽出
_STOCK_VAL_RE = re.compile(r"stock_val_1_(\d{6})")
_FUTURES_RE   = re.compile(r"Tousi_DV_W_(\d{6})_\d+_(\d{4})_(\d{4})")


@dataclass
class WeekInfo:
    year: int
    month: int        # 「YY年MM月第N週」の MM
    week_num: int     # 「第N週」の N
    week_start: date  # 月曜
    week_end: date    # 金曜


def _decode(resp: requests.Response) -> str:
    """JPXページは UTF-8 だが requests が ISO-8859-1 と誤判定するため明示デコード"""
    return resp.content.decode("utf-8", errors="replace")


def _parse_pairs(html: str, fname_re: re.Pattern) -> dict[str, WeekInfo]:
    """HTML から {ファイル名stem: WeekInfo} を抽出する。
    fname_re はマッチ全体のファイル名の前にある「直前の期間表記」を拾うのに使う。
    """
    out: dict[str, WeekInfo] = {}
    for m in fname_re.finditer(html):
        fname = m.group(0)  # stock_val_1_260502 等
        idx = m.start()
        # 直前 3000 文字以内に書かれている最終の週情報を採用
        ctx = html[max(0, idx - 3000): idx]
        ws = list(_WEEK_RE.finditer(ctx))
        if not ws:
            continue
        last = ws[-1]
        year, mm, ww, sm, sd, em, ed = (int(x) for x in last.groups())
        # 月をまたぐ週（例: 4/27〜5/1）に対応
        end_year = year if em >= sm else year + 1
        try:
            ws_start = date(year, sm, sd)
            ws_end   = date(end_year, em, ed)
        except ValueError:
            continue
        out[fname] = WeekInfo(
            year=year, month=mm, week_num=ww,
            week_start=ws_start, week_end=ws_end,
        )
    return out


def resolve_from_jpx(timeout: int = 30) -> dict[str, WeekInfo]:
    """JPXの現物・先物両インデックスから {filename_stem: WeekInfo} を取得。
    現物の stem: 'stock_val_1_YYMMWW'
    先物の stem: 'Tousi_DV_W_YYYYMM_X_MMDD_MMDD'
    """
    mapping: dict[str, WeekInfo] = {}

    # 現物
    try:
        r = requests.get(JPX_SPOT_INDEX, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        html = _decode(r)
        mapping.update(_parse_pairs(html, _STOCK_VAL_RE))
    except Exception as e:
        logger.warning(f"[JPX現物] HTML取得失敗: {e}")

    # 先物
    try:
        r = requests.get(JPX_FUTURES_INDEX, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        html = _decode(r)
        mapping.update(_parse_pairs(html, _FUTURES_RE))
    except Exception as e:
        logger.warning(f"[JPX先物] HTML取得失敗: {e}")

    return mapping


def extract_filename_stem(source_url: str) -> Optional[str]:
    """source_url から ファイル名 stem を抽出（拡張子なし、パスなし）"""
    if not source_url:
        return None
    # URL or manual:path 形式
    tail = source_url.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    tail = tail.split("?")[0]
    # 拡張子除去
    stem = tail.rsplit(".", 1)[0]
    return stem or None


if __name__ == "__main__":
    # CLI: JPXの現在のマッピングを出力
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    mapping = resolve_from_jpx()
    print(f"=== JPX 公開中のマッピング ({len(mapping)} 件) ===")
    for stem, wi in sorted(mapping.items(), key=lambda x: x[1].week_end, reverse=True):
        print(f"  {stem}: {wi.week_start} 〜 {wi.week_end}  ({wi.year}年{wi.month}月第{wi.week_num}週)")
