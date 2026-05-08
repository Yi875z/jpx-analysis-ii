"""
Supabase データ取得モジュール
既存の config/.env から接続情報を読み込む
"""
import os
from pathlib import Path
import pandas as pd
import streamlit as st
from supabase import create_client, Client
from dotenv import load_dotenv

# プロジェクトルートの config/.env を読み込む
_ENV_PATH = Path(__file__).parent.parent.parent / "config" / ".env"
load_dotenv(_ENV_PATH)

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY", "")


@st.cache_resource
def _client() -> Client:
    if not _SUPABASE_URL or not _SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_SERVICE_KEY が config/.env に設定されていません"
        )
    return create_client(_SUPABASE_URL, _SUPABASE_KEY)


_PAGE_SIZE = 1000  # Supabase max-rows 上限

def _fetch(table: str, columns: str, weeks: int | None = None, months: int | None = None) -> pd.DataFrame:
    """ページネーションで全件取得。Supabaseのmax-rows=1000制限を回避する"""
    try:
        client = _client()

        cutoff = None
        if weeks is not None:
            cutoff = (pd.Timestamp.today() - pd.DateOffset(weeks=weeks)).strftime("%Y-%m-%d")
        elif months is not None:
            cutoff = (pd.Timestamp.today() - pd.DateOffset(months=months)).strftime("%Y-%m-%d")

        all_rows: list = []
        offset = 0
        while True:
            q = client.table(table).select(columns).order("week_date", desc=False)
            if cutoff:
                q = q.gte("week_date", cutoff)
            resp = q.range(offset, offset + _PAGE_SIZE - 1).execute()
            rows = resp.data or []
            all_rows.extend(rows)
            if len(rows) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

        if not all_rows:
            return pd.DataFrame()
        df = pd.DataFrame(all_rows)
        if "week_date" in df.columns:
            df["week_date"] = pd.to_datetime(df["week_date"])
        return df
    except Exception as e:
        st.error(f"Supabase 接続エラー ({table}): {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def get_weekly_spot(weeks: int = 52) -> pd.DataFrame:
    return _fetch(
        "weekly_spot",
        "week_date,investor_type,market,buy_amount,sell_amount,net_amount",
        weeks=weeks,
    )


@st.cache_data(ttl=3600)
def get_weekly_futures(weeks: int = 52) -> pd.DataFrame:
    return _fetch(
        "weekly_futures",
        "week_date,investor_type,futures_type,long_lots,short_lots,net_lots,net_amount_oku",
        weeks=weeks,
    )


@st.cache_data(ttl=3600)
def get_weekly_combined(weeks: int = 52) -> pd.DataFrame:
    return _fetch(
        "weekly_combined",
        "week_date,investor_type,spot_net,futures_net_oku,combined_net,is_twin_engine",
        weeks=weeks,
    )


@st.cache_data(ttl=3600)
def get_weekly_stats(weeks: int = 52) -> pd.DataFrame:
    return _fetch(
        "weekly_stats",
        "week_date,investor_type,data_type,net_amount,zscore_26w,zscore_52w,ma4w,wow_change",
        weeks=weeks,
    )


@st.cache_data(ttl=3600)
def get_monthly_summary(months: int = 12) -> pd.DataFrame:
    return _fetch(
        "monthly_summary",
        "year_month,investor_type,spot_net_sum,futures_net_sum,combined_net",
        months=months,
    )


@st.cache_data(ttl=3600)
def get_latest_week_date() -> str:
    try:
        client = _client()
        resp = client.table("weekly_spot").select("week_date").order("week_date", desc=True).limit(1).execute()
        if resp.data:
            return resp.data[0]["week_date"]
    except Exception as e:
        st.error(f"最新週日付の取得に失敗: {e}")
    return "不明"
