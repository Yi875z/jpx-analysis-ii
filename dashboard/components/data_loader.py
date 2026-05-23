"""
Supabase データ取得モジュール
既存の config/.env から接続情報を読み込む
"""
import os
import re
from pathlib import Path
import pandas as pd
import streamlit as st
from supabase import create_client, Client
from dotenv import load_dotenv

# プロジェクトルートの config/.env を読み込む
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_ENV_PATH = _PROJECT_ROOT / "config" / ".env"
load_dotenv(_ENV_PATH)

_REPORTS_DIR = _PROJECT_ROOT / "outputs" / "reports"

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


# ─────────────────────────────────────────────────────────────────
# AIレポート取得（Supabase reports テーブル + outputs/reports/ ファイル）
# ─────────────────────────────────────────────────────────────────

# 週次ファイル名は2形式に対応:
#   旧: jpx_investor_YYYYMMDD.md      （週末日のみ）
#   新: jpx_investor_YYYYMMDD_YYYYMMDD.md （週初_週末）
_WEEKLY_FNAME_RE_NEW = re.compile(r"jpx_investor_(\d{8})_(\d{8})\.md$")
_WEEKLY_FNAME_RE_OLD = re.compile(r"jpx_investor_(\d{8})\.md$")
_MONTHLY_FNAME_RE    = re.compile(r"jpx_monthly_(\d{6})\.md$")


def _normalize_report_id(week_date: str, report_type: str) -> str:
    """週次は YYYY-MM-DD、月次は YYYY-MM 形式に正規化"""
    if report_type == "weekly":
        return week_date
    return week_date[:7]  # 月次は月末日が入っていても YYYY-MM に揃える


@st.cache_data(ttl=600)
def get_report_list(report_type: str = "weekly") -> list[dict]:
    """利用可能なレポート一覧を取得。DB + ファイルシステムを統合。

    返り値: [{"id": "YYYY-MM-DD" or "YYYY-MM", "source": "db"|"file", "file_name": str}, ...]
    """
    items: dict[str, dict] = {}

    # ① DB から
    try:
        client = _client()
        resp = (client.table("reports")
                .select("week_date,format,file_name")
                .eq("report_type", report_type)
                .eq("format", "markdown")
                .order("week_date", desc=True)
                .execute())
        for r in resp.data or []:
            rid = _normalize_report_id(r["week_date"], report_type)
            items[rid] = {
                "id": rid,
                "week_date": r["week_date"],
                "source": "db",
                "file_name": r.get("file_name") or "",
            }
    except Exception as e:
        st.warning(f"reports テーブルの読み込みに失敗: {e}")

    # ② ファイルシステムから補完
    if _REPORTS_DIR.exists():
        if report_type == "weekly":
            for f in _REPORTS_DIR.glob("jpx_investor_*.md"):
                # 新フォーマット優先: YYYYMMDD_YYYYMMDD（週末日を id に使う）
                m_new = _WEEKLY_FNAME_RE_NEW.search(f.name)
                if m_new:
                    s = m_new.group(2)  # 週末日
                else:
                    m_old = _WEEKLY_FNAME_RE_OLD.search(f.name)
                    if not m_old:
                        continue
                    s = m_old.group(1)
                rid = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
                if rid not in items:
                    items[rid] = {
                        "id": rid,
                        "week_date": rid,
                        "source": "file",
                        "file_name": f.name,
                    }
        else:
            for f in _REPORTS_DIR.glob("jpx_monthly_*.md"):
                m = _MONTHLY_FNAME_RE.search(f.name)
                if not m:
                    continue
                s = m.group(1)
                rid = f"{s[:4]}-{s[4:6]}"
                if rid not in items:
                    items[rid] = {
                        "id": rid,
                        "week_date": rid,
                        "source": "file",
                        "file_name": f.name,
                    }

    return sorted(items.values(), key=lambda x: x["id"], reverse=True)


@st.cache_data(ttl=600)
def get_report_content(report_id: str, report_type: str = "weekly") -> str:
    """指定レポートの本文（Markdown）を返す。DB → ファイルの順にフォールバック。

    report_id: weekly なら YYYY-MM-DD、monthly なら YYYY-MM
    """
    # ① DB から
    try:
        client = _client()
        q = (client.table("reports")
             .select("content_md")
             .eq("report_type", report_type)
             .eq("format", "markdown"))
        if report_type == "weekly":
            q = q.eq("week_date", report_id)
        else:
            q = q.like("week_date", f"{report_id}-%")
        resp = q.limit(1).execute()
        if resp.data and resp.data[0].get("content_md"):
            return resp.data[0]["content_md"]
    except Exception:
        pass

    # ② ファイルから
    if report_type == "weekly":
        fname = f"jpx_investor_{report_id.replace('-', '')}.md"
    else:
        fname = f"jpx_monthly_{report_id.replace('-', '')}.md"
    fpath = _REPORTS_DIR / fname
    if fpath.exists():
        return fpath.read_text(encoding="utf-8")
    return ""


def extract_executive_summary(md: str) -> str:
    """レポートMarkdownからエグゼクティブサマリー部分のみ抽出"""
    if not md:
        return ""
    lines = md.split("\n")
    out: list[str] = []
    in_summary = False
    for line in lines:
        stripped = line.lstrip("#").strip()
        # サマリー開始
        if line.startswith("##") and "エグゼクティブサマリー" in stripped:
            in_summary = True
            continue
        # 次の見出しでサマリー終了
        if in_summary and line.startswith("##"):
            break
        # サマリー終了マーカー（---）
        if in_summary and line.strip() == "---":
            break
        if in_summary:
            out.append(line)
    return "\n".join(out).strip()
