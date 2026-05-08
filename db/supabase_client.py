"""
db/supabase_client.py
Supabaseへの全CRUD操作を集約したモジュール
"""

import os
from datetime import date, datetime
from typing import Optional
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]
        _client = create_client(url, key)
    return _client


# ─────────────────────────────────────────
# 書き込み系
# ─────────────────────────────────────────

def upsert_spot(rows: list[dict]) -> int:
    """現物週次データをupsert（week_date + investor_type + market でユニーク）"""
    if not rows:
        return 0
    sb = get_client()
    sb.table("weekly_spot").upsert(rows, on_conflict="week_date,investor_type,market").execute()
    return len(rows)


def upsert_futures(rows: list[dict]) -> int:
    """先物週次データをupsert"""
    if not rows:
        return 0
    sb = get_client()
    sb.table("weekly_futures").upsert(rows, on_conflict="week_date,investor_type,futures_type").execute()
    return len(rows)


def upsert_combined(rows: list[dict]) -> int:
    """合算データをupsert"""
    if not rows:
        return 0
    sb = get_client()
    sb.table("weekly_combined").upsert(rows, on_conflict="week_date,investor_type").execute()
    return len(rows)


def upsert_stats(rows: list[dict]) -> int:
    """統計キャッシュをupsert"""
    if not rows:
        return 0
    sb = get_client()
    sb.table("weekly_stats").upsert(rows, on_conflict="week_date,investor_type,data_type").execute()
    return len(rows)


def upsert_monthly(rows: list[dict]) -> int:
    """月次サマリーをupsert"""
    if not rows:
        return 0
    sb = get_client()
    sb.table("monthly_summary").upsert(rows, on_conflict="year_month,investor_type").execute()
    return len(rows)


def save_report(week_date: date, report_type: str, fmt: str,
                file_name: str, content_md: str = "", gdrive_url: str = "") -> None:
    """レポートメタデータを保存"""
    sb = get_client()
    sb.table("reports").upsert({
        "week_date": str(week_date),
        "report_type": report_type,
        "format": fmt,
        "file_name": file_name,
        "content_md": content_md,
        "gdrive_url": gdrive_url,
    }, on_conflict="week_date,report_type,format").execute()


def save_log(week_date: Optional[date], status: str, spot_rows: int = 0,
             futures_rows: int = 0, error_message: str = "", duration_sec: float = 0.0) -> None:
    """実行ログを保存"""
    sb = get_client()
    sb.table("fetch_logs").insert({
        "week_date": str(week_date) if week_date else None,
        "status": status,
        "spot_rows": spot_rows,
        "futures_rows": futures_rows,
        "error_message": error_message,
        "duration_sec": round(duration_sec, 2),
    }).execute()


# ─────────────────────────────────────────
# 読み取り系
# ─────────────────────────────────────────

def fetch_spot_history(investor_type: str, weeks: int = 52) -> list[dict]:
    """現物の過去N週データを取得"""
    sb = get_client()
    res = (sb.table("weekly_spot")
             .select("week_date,investor_type,net_amount,buy_amount,sell_amount")
             .eq("investor_type", investor_type)
             .eq("market", "prime")
             .order("week_date", desc=True)
             .limit(weeks)
             .execute())
    return res.data or []


def fetch_futures_history(investor_type: str, weeks: int = 52) -> list[dict]:
    """先物の過去N週データを取得"""
    sb = get_client()
    res = (sb.table("weekly_futures")
             .select("week_date,net_lots,net_amount_oku,futures_type")
             .eq("investor_type", investor_type)
             .order("week_date", desc=True)
             .limit(weeks)
             .execute())
    return res.data or []


def fetch_latest_week() -> Optional[date]:
    """DBに蓄積済みの最新week_dateを返す"""
    sb = get_client()
    res = (sb.table("weekly_spot")
             .select("week_date")
             .order("week_date", desc=True)
             .limit(1)
             .execute())
    if res.data:
        return date.fromisoformat(res.data[0]["week_date"])
    return None


def fetch_week_spot(week_date: date) -> list[dict]:
    """指定週の現物データを全投資家区分で取得"""
    sb = get_client()
    res = (sb.table("weekly_spot")
             .select("*")
             .eq("week_date", str(week_date))
             .execute())
    return res.data or []


def fetch_week_futures(week_date: date) -> list[dict]:
    """指定週の先物データを全投資家区分で取得"""
    sb = get_client()
    res = (sb.table("weekly_futures")
             .select("*")
             .eq("week_date", str(week_date))
             .execute())
    return res.data or []


def fetch_combined_history(weeks: int = 26) -> list[dict]:
    """合算データの過去N週（全投資家区分）"""
    sb = get_client()
    res = (sb.table("weekly_combined")
             .select("*")
             .order("week_date", desc=True)
             .limit(weeks * 5)   # 5投資家区分
             .execute())
    return res.data or []


def fetch_stats_history(data_type: str = "spot", weeks: int = 260) -> list[dict]:
    """weekly_statsの過去N週分を取得（Zスコア・MA含む）"""
    sb = get_client()
    res = (sb.table("weekly_stats")
             .select("week_date,investor_type,data_type,net_amount,zscore_26w,zscore_52w,ma4w,wow_change")
             .eq("data_type", data_type)
             .order("week_date", desc=True)
             .limit(weeks * 6)   # 6投資家区分
             .execute())
    return res.data or []


def fetch_monthly_summary(months: int = 12) -> list[dict]:
    """月次サマリー過去N月"""
    sb = get_client()
    res = (sb.table("monthly_summary")
             .select("*")
             .order("year_month", desc=True)
             .limit(months * 6)   # 6投資家区分
             .execute())
    return res.data or []
