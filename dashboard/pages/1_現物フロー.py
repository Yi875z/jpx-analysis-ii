"""
現物フロー分析ページ
投資家別NET推移（折れ線）+ 買い越し/売り越し（棒グラフ）
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from components.data_loader import get_weekly_spot
from components.charts import COLORS
from components.theme import render_theme_toggle, plot_layout

st.set_page_config(page_title="現物フロー｜JPX投資主体別売買動向ダッシュボード", layout="wide")
st.title("📈 現物フロー")

# ─── サイドバー フィルター ────────────────────────────────────
with st.sidebar:
    st.markdown("### 表示設定")
    period = st.radio("表示期間", [4, 13, 26, 52], index=2, format_func=lambda w: f"{w}週")

    ALL_INVESTORS = {
        "foreign":    "外国人",
        "trust_bank": "信託銀行",
        "individual": "個人",
        "corporate":  "事業法人",
        "dealer":     "自己",
    }
    selected = st.multiselect(
        "投資家フィルター",
        options=list(ALL_INVESTORS.keys()),
        default=["foreign", "trust_bank", "individual"],
        format_func=lambda k: ALL_INVESTORS[k],
    )
    market_opt = st.selectbox("市場", ["合計", "東証プライム", "東証スタンダード"])
    st.divider()
    render_theme_toggle()
    st.divider()
    if st.button("キャッシュ更新"):
        st.cache_data.clear()
        st.rerun()

# ─── データ取得 ────────────────────────────────────────────────
df = get_weekly_spot(weeks=period)

if df.empty:
    st.info("データがありません。まずデータ取得スクリプトを実行してください。")
    st.stop()

if market_opt != "合計" and "market" in df.columns:
    df = df[df["market"] == market_opt]

df_filtered = df[df["investor_type"].isin(selected)].copy()
df_filtered["week_label"] = pd.to_datetime(df_filtered["week_date"]).dt.strftime("%m/%d")

# ─── グラフ1: 投資家別NET推移（折れ線） ──────────────────────
st.subheader("投資家別 NET推移（億円）")

fig_line = go.Figure()
for inv_key in selected:
    label = ALL_INVESTORS[inv_key]
    sub = df_filtered[df_filtered["investor_type"] == inv_key].sort_values("week_date")
    if sub.empty:
        continue
    inv_color = COLORS.get(label, "#aaaaaa")
    fig_line.add_trace(go.Scatter(
        x=sub["week_label"],
        y=sub["net_amount"],
        mode="lines+markers",
        name=label,
        line=dict(color=inv_color, width=2),
        marker=dict(size=6),
        hovertemplate=f"{label}<br>%{{x}}: %{{y:,.0f}}億円<extra></extra>",
        hoverlabel=dict(bgcolor=inv_color, font=dict(color="#ffffff", size=13), bordercolor="rgba(0,0,0,0)"),
    ))

fig_line.update_layout(
    **plot_layout(
        xaxis=dict(title="週末日"),
        yaxis=dict(title="NET（億円）"),
        height=400,
    )
)
st.plotly_chart(fig_line, use_container_width=True)

# ─── グラフ2: 投資家別 買い越し/売り越し棒グラフ ──────────────
st.subheader("投資家別 買い越し / 売り越し（億円）")

inv_tab_keys = [k for k in selected if not df_filtered[df_filtered["investor_type"] == k].empty]
if inv_tab_keys:
    tabs = st.tabs([ALL_INVESTORS[k] for k in inv_tab_keys])
    for tab, inv_key in zip(tabs, inv_tab_keys):
        with tab:
            label = ALL_INVESTORS[inv_key]
            sub = df_filtered[df_filtered["investor_type"] == inv_key].sort_values("week_date")
            vals = list(sub["net_amount"])
            bar_colors = [COLORS["positive"] if v >= 0 else COLORS["negative"] for v in vals]
            fig_bar = go.Figure(go.Bar(
                x=sub["week_label"],
                y=sub["net_amount"],
                marker_color=bar_colors,
                hovertemplate="%{x}: %{y:,.0f}億円<extra></extra>",
                hoverlabel=dict(
                    bgcolor=[COLORS["positive"] if v >= 0 else COLORS["negative"] for v in vals],
                    font=dict(color="#ffffff", size=13),
                    bordercolor="rgba(0,0,0,0)",
                ),
            ))
            fig_bar.update_layout(
                **plot_layout(
                    xaxis=dict(title="週末日"),
                    yaxis=dict(title="NET（億円）"),
                    height=350,
                )
            )
            st.plotly_chart(fig_bar, use_container_width=True)
