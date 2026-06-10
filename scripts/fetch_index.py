"""
指数終値取得モジュール（日経225 / TOPIX）。

JPX先物CSVには現物指数の水準が含まれないため、AIレポートが価格目標を
語る際の根拠（アンカー）として実勢の指数終値を外部から取得する。
これが無いと、月次レポートのシナリオがモデルの学習記憶（古い株価水準）に
引きずられて実勢とかけ離れた価格を出すハルシネーションが起きる。

データソース: Yahoo Finance チャートAPI（APIキー不要・requestsのみ）。
取得失敗時は None を返し、パイプラインを止めない（価格欠落 < クラッシュ）。
"""
import logging
from datetime import date, datetime, timedelta

import requests

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# Yahoo Finance シンボル
SYMBOLS = {
    "nikkei225": "^N225",
    "topix":     "1306.T",  # TOPIX連動ETF（^TOPXは取得不可な場合があるためETFで代替）
}

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def _fetch_daily_closes(symbol: str, range_: str = "3mo") -> list[tuple[date, float]]:
    """指定シンボルの日次終値を (date, close) の昇順リストで返す。失敗時は空リスト。"""
    url = _CHART_URL.format(symbol=symbol)
    try:
        resp = requests.get(
            url, params={"range": range_, "interval": "1d"},
            headers=HEADERS, timeout=20,
        )
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except Exception as e:
        logger.warning(f"[指数取得失敗] {symbol}: {e}")
        return []

    out: list[tuple[date, float]] = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        d = datetime.utcfromtimestamp(ts).date()
        out.append((d, round(float(close), 2)))
    out.sort(key=lambda x: x[0])
    return out


def get_close_on_or_before(target: date, key: str = "nikkei225",
                           max_back_days: int = 10) -> tuple[date, float] | None:
    """target 日（含む）以前で直近の終値を (約定日, 終値) で返す。

    target が休場日でも max_back_days 日まで遡って直近営業日の終値を拾う。
    取得不能な場合は None。
    """
    symbol = SYMBOLS.get(key)
    if symbol is None:
        logger.warning(f"[指数取得] 未知のキー: {key}")
        return None

    # target が古い場合に備え range を広めに取る
    delta_days = (date.today() - target).days
    range_ = "3mo" if delta_days <= 80 else ("1y" if delta_days <= 350 else "2y")

    series = _fetch_daily_closes(symbol, range_)
    if not series:
        return None

    cutoff = target - timedelta(days=max_back_days)
    candidates = [(d, c) for d, c in series if cutoff <= d <= target]
    if not candidates:
        return None
    return max(candidates, key=lambda x: x[0])


def get_latest_close(key: str = "nikkei225") -> tuple[date, float] | None:
    """最新の終値を (約定日, 終値) で返す。取得不能なら None。"""
    series = _fetch_daily_closes(SYMBOLS.get(key, ""), "5d")
    if not series:
        return None
    return series[-1]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("latest nikkei225 :", get_latest_close("nikkei225"))
    print("2026-05-31 close :", get_close_on_or_before(date(2026, 5, 31), "nikkei225"))
