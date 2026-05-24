"""
JPX投資主体別売買動向ダッシュボード
トップ画面: 最新週KPI・ツインエンジン判定・4週トレンドグラフ
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# ─── Streamlit Cloud パスワード保護（ローカル実行時はスキップ） ─────
# Cloud デプロイ時のみ st.secrets に [auth] セクションがある想定。
# 詳細手順は DEPLOY.md 参照。
try:
    _has_auth = hasattr(st, "secrets") and "auth" in st.secrets
except Exception:
    _has_auth = False
if _has_auth:
    try:
        import streamlit_authenticator as _stauth
        _cfg = st.secrets["auth"]
        _authenticator = _stauth.Authenticate(
            credentials={"usernames": {_cfg["username"]: {
                "name":     _cfg["username"],
                "password": _cfg["password_hash"],
            }}},
            cookie_name=_cfg["cookie_name"],
            key=_cfg["cookie_key"],
            cookie_expiry_days=int(_cfg.get("cookie_expiry_days", 30)),
        )
        _authenticator.login("main")
        if not st.session_state.get("authentication_status"):
            st.error("ログインしてください")
            st.stop()
    except ImportError:
        st.warning("streamlit-authenticator がインストールされていません")

from components.data_loader import (
    get_weekly_spot,
    get_weekly_combined,
    get_latest_week_date,
    get_report_list,
    get_report_content,
    extract_executive_summary,
)
from components.metrics import latest_net, prev_net, wow_delta, format_oku
from components.charts import COLORS
from components.theme import render_theme_toggle, plot_layout, get_theme

st.set_page_config(
    page_title="JPX投資主体別売買動向ダッシュボード",
    page_icon="📊",
    layout="wide",
)

# ─── ヘッダー ─────────────────────────────────────────────────
latest_week = get_latest_week_date()
try:
    latest_dt = pd.to_datetime(latest_week)
    weekday_ja = ["月", "火", "水", "木", "金", "土", "日"][latest_dt.weekday()]
    week_label = f"{latest_dt.strftime('%Y-%m-%d')}（{weekday_ja}曜日）"
except Exception:
    week_label = latest_week

st.title("📊 JPX投資主体別売買動向ダッシュボード")
st.caption(f"最新週: {week_label}")

# ─── アラート表示 ─────────────────────────────────────────────
import json
from pathlib import Path as _Path
_ALERT_PATH = _Path(__file__).parent.parent / "outputs" / "alerts" / "latest.json"
if _ALERT_PATH.exists():
    try:
        _ar = json.loads(_ALERT_PATH.read_text(encoding="utf-8"))
        _alerts = _ar.get("alerts", [])
        if _alerts:
            high_count = sum(1 for a in _alerts if a.get("level") == "high")
            med_count  = sum(1 for a in _alerts if a.get("level") == "medium")
            st.markdown(
                f"""<div style="background:#fff5e6;border-left:4px solid #ff6b35;
                padding:10px 16px;border-radius:6px;margin-bottom:8px;color:#5a2a00;">
                ⚠️ <b>アクティブアラート: {len(_alerts)} 件</b>
                （HIGH: {high_count} / MEDIUM: {med_count}） — {_ar.get("week_date", "")} 週評価
                </div>""", unsafe_allow_html=True)
            with st.expander("🔔 アラート詳細を表示", expanded=False):
                for a in _alerts:
                    color = "#e63946" if a.get("level") == "high" else "#f5a623"
                    st.markdown(
                        f"""<div style="border-left:3px solid {color};padding:6px 12px;margin:6px 0;">
                        <b>[{a['level'].upper()}] {a['title']}</b><br>
                        <span style="color:#666;font-size:13px;">{a.get('message','')}</span>
                        </div>""", unsafe_allow_html=True)
                st.caption(f"閾値: {_ar.get('thresholds', {})}")
    except Exception:
        pass

st.divider()

# ─── データ取得 ────────────────────────────────────────────────
spot_df     = get_weekly_spot(weeks=8)
combined_df = get_weekly_combined(weeks=8)

# KPIカード用（外国人 / 信託銀行 / 個人）
KPI_TARGETS = [
    ("foreign",     "外国人"),
    ("trust_bank",  "信託銀行"),
    ("individual",  "個人"),
]
# グラフ用（5投資家全員）
CHART_TARGETS = [
    ("foreign",     "外国人"),
    ("trust_bank",  "信託銀行"),
    ("individual",  "個人"),
    ("corporate",   "事業法人"),
    ("dealer",      "自己"),
]

t = get_theme()  # デフォルト: light

# KPIカード色クラス: 高特異度セレクターでStreamlit内部CSSに勝つ
st.markdown("""
<style>
.kpi-pos, [data-testid="stMarkdownContainer"] .kpi-pos,
.block-container [data-testid="stMarkdownContainer"] .kpi-pos {
    color: #2dc653 !important;
}
.kpi-neg, [data-testid="stMarkdownContainer"] .kpi-neg,
.block-container [data-testid="stMarkdownContainer"] .kpi-neg {
    color: #e63946 !important;
}
</style>
""", unsafe_allow_html=True)

cols = st.columns(3)
for col, (inv_key, inv_label) in zip(cols, KPI_TARGETS):
    cur   = latest_net(spot_df, inv_key)
    prev  = prev_net(spot_df, inv_key)
    delta, arrow, _ = wow_delta(cur, prev)
    val_cls   = "kpi-pos" if cur   >= 0 else "kpi-neg"
    delta_cls = "kpi-pos" if delta >= 0 else "kpi-neg"
    border_color = "#2dc653" if cur >= 0 else "#e63946"
    with col:
        st.markdown(
            f"""
            <div style="background:{t['bg2']};border-radius:8px;padding:16px 20px;border-left:4px solid {border_color}">
              <div style="color:{t['subtext']};font-size:13px;margin-bottom:6px">{inv_label}</div>
              <div class="{val_cls}" style="font-size:28px;font-weight:bold;letter-spacing:1px">{format_oku(cur)}</div>
              <div class="{delta_cls}" style="font-size:13px;margin-top:6px">{arrow} {format_oku(delta)}&nbsp;前週比</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.divider()

# ─── ツインエンジン判定 ────────────────────────────────────────
if not combined_df.empty:
    latest_combined = (
        combined_df[combined_df["investor_type"] == "foreign"]
        .sort_values("week_date")
        .iloc[-1] if "foreign" in combined_df["investor_type"].values else None
    )
    if latest_combined is not None:
        is_twin = latest_combined.get("is_twin_engine", False)
        if is_twin:
            st.success("ツインエンジン: 🟢 ON  ─ 外国人が現物・先物ともに買い越し")
        else:
            st.info("ツインエンジン: ⚪ OFF ─ 現物・先物どちらかが売り越し")
    else:
        st.warning("ツインエンジンデータが見つかりません")
else:
    st.warning("weekly_combined テーブルにデータがありません")

st.divider()

# ─── 最新AIレポートのサマリー ──────────────────────────────────
_weekly_reports = get_report_list(report_type="weekly")
if _weekly_reports:
    _latest_rid = _weekly_reports[0]["id"]
    _latest_md  = get_report_content(_latest_rid, report_type="weekly")
    if _latest_md:
        _summary = extract_executive_summary(_latest_md)
        with st.expander(f"📋 AI需給サマリー（{_latest_rid}週）— クリックで展開", expanded=True):
            if _summary:
                st.markdown(_summary)
            else:
                st.caption("エグゼクティブサマリーを抽出できませんでした。全文は「📋 6_AIレポート」ページで閲覧してください。")
            st.caption("👈 全文・過去レポートは左サイドバーの **「6_AIレポート」** ページから")
    else:
        st.info("最新AIレポートが見つかりません。`python main.py` を実行してください。")
else:
    st.info("AIレポートがまだありません。`python main.py` を実行してください。")

st.divider()

# ─── 直近4週トレンドグラフ ────────────────────────────────────
st.subheader("4週間 現物・先物合算NET推移（億円）")

if combined_df.empty:
    st.info("データがありません。まずデータ取得スクリプトを実行してください。")
else:
    fig = go.Figure()
    for inv_key, inv_label in CHART_TARGETS:
        sub = combined_df[combined_df["investor_type"] == inv_key].sort_values("week_date")
        if sub.empty:
            continue
        color = COLORS.get(inv_label, "#aaaaaa")
        vals = list(sub["combined_net"])
        fig.add_trace(go.Bar(
            name=inv_label,
            x=sub["week_date"].dt.strftime("%m/%d"),
            y=sub["combined_net"],
            marker_color=color,
            hovertemplate=f"{inv_label}<br>%{{x}}: %{{y:,.0f}}億円<extra></extra>",
            hoverlabel=dict(
                bgcolor=[COLORS["positive"] if v >= 0 else COLORS["negative"] for v in vals],
                font=dict(color="#ffffff", size=13),
                bordercolor="rgba(0,0,0,0)",
            ),
            opacity=0.85,
        ))

    fig.update_layout(
        barmode="group",
        **plot_layout(
            xaxis=dict(title="週末日"),
            yaxis=dict(title="NET（億円）"),
            height=380,
        ),
    )
    st.plotly_chart(fig, use_container_width=True)

# ─── サイドバーナビ案内 ────────────────────────────────────────
with st.sidebar:
    st.markdown("### ナビゲーション")
    st.markdown("""
- 🏠 **ホーム** (現在)
- 📈 1_現物フロー
- 📉 2_先物フロー
- ⚡ 3_合算分析
- 📊 4_Zスコア
- 📅 5_月次集計
- 📋 6_AIレポート
- 🎯 7_オプション
""")
    st.divider()
    render_theme_toggle()
    st.divider()
    if st.button("キャッシュ更新"):
        st.cache_data.clear()
        st.rerun()
