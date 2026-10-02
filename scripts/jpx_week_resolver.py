"""
scripts/jpx_week_resolver.py
============================
JPXインデックスページから「ファイル名 → 対象週末日」のマッピングを取得する。

JPXのファイル名規則は単純な「月内第N金曜」では再現できないため、
HTMLに記載されている期間表記（YYYY年MM月第N週(MM月DD日〜MM月DD日)）を
正規表現で直接抽出して対応関係を作る。

提供API:
  resolve_from_jpx() -> {filename_stem: WeekInfo}
  spot_week_end_from_filename(url) -> date | None   … 新形式の現物ファイル名から週末日
  spot_files_by_week(html) -> {週末日: URL}          … 現物ページの新旧両形式を週末日で引く
  unreported_weeks(published, latest, exists) -> [週末日]

現物のファイル名は 2026-09-29 掲載分から変わった:
  旧: stock_val_1_YYMMNN.xls（「YY年MM月第NN週」。週末日はページの期間表記で引く）
  新: stock_1_w_YYYYMMDD_YYYYMMDD.xlsx（開始日_終了日。ファイル名だけで週末日が決まる）
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
_STOCK_W_RE   = re.compile(r"stock_1_w_(\d{8})_(\d{8})")

# 現物ページで対象にするリンク（金額の旧形式／新形式）。
# 旧形式の株数ファイル stock_vol_*、見本の stock_1_w_YYYYMMDD_YYYYMMDD.xlsx は拾わない。
_SPOT_HREF_RE = re.compile(
    r'href="([^"]*?(?:stock_1_w_\d{8}_\d{8}\.xlsx|stock_val_1_\d{6}\.xls))"', re.IGNORECASE
)

JPX_BASE = "https://www.jpx.co.jp"


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


def spot_week_end_from_filename(url: str) -> Optional[date]:
    """新形式の現物ファイル名（stock_1_w_開始日_終了日）から週末日（終了日）を返す。
    旧形式など読めない名前なら None。"""
    m = _STOCK_W_RE.search(url or "")
    if not m:
        return None
    end = m.group(2)
    try:
        return date(int(end[:4]), int(end[4:6]), int(end[6:8]))
    except ValueError:
        return None


def spot_files_by_week(html: str) -> dict[date, str]:
    """JPX現物ページの HTML から {週末日: ファイルURL} を作る（新旧両形式）。

    新形式はファイル名の終了日、旧形式はページの期間表記で週末日を決める。
    どちらでも週末日を決められないリンクは推測で埋めずに捨てる（警告ログを出す）。
    """
    old_map = _parse_pairs(html, _STOCK_VAL_RE)
    out: dict[date, str] = {}
    for m in _SPOT_HREF_RE.finditer(html):
        href = m.group(1)
        url = href if href.startswith("http") else JPX_BASE + href
        week_end = spot_week_end_from_filename(url)
        if week_end is None:
            wi = old_map.get(extract_filename_stem(url) or "")
            week_end = wi.week_end if wi else None
        if week_end is None:
            logger.warning(f"[JPX現物] 対象週を特定できないリンクを除外: {url}")
            continue
        out.setdefault(week_end, url)
    return out


def unreported_weeks(published: list[date], latest: date, report_exists) -> list[date]:
    """JPXに掲載中で latest より古いのにレポートが無い週を古い順に返す。

    自動実行は最新の1週しか処理しないので、実行と実行の間に2週分が公表されると
    古い方を黙って飛ばす（2026-09: 連休明けに 9/18週と9/25週が続けて公表され 9/18週が欠落）。
    """
    return sorted(w for w in set(published) if w < latest and not report_exists(w))


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
