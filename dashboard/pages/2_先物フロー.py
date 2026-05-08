"""
先物フロー分析ページ
日経225先物 / TOPIX先物 切り替えタブ
NET（ロット）推移 + NET（億円）推移
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from components.data_loader import get_weekly_futures
from components.charts import COLORS, INV_BAR_COLORS
from components.theme import render_theme_toggle, plot_layout

st.set_page_config(page_title="先物フロー｜JPX投資主体別売買動向ダッシュボード", layout="wide")
st.title("📉 先物フロー")

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
    st.divider()
    render_theme_toggle()
    st.divider()
    if st.button("キャッシュ更新"):
        st.cache_data.clear()
        st.rerun()

# ─── データ取得 ────────────────────────────────────────────────
df = get_weekly_futures(weeks=period)

if df.empty:
    st.info("データがありません。まずデータ取得スクリプトを実行してください。")
    st.stop()

FUTURES_MAP = {
    "nikkei225_large": "日経225先物",
    "topix_large":     "TOPIX先物",
}

tab_nikkei, tab_topix = st.tabs(["🗾 日経225先物", "📊 TOPIX先物"])

def _render_futures_tab(tab, futures_key: str, futures_label: str):
    with tab:
        df_f = df[
            (df["futures_type"] == futures_key) &
            (df["investor_type"].isin(selected))
        ].copy()
        df_f["week_label"] = pd.to_datetime(df_f["week_date"]).dt.strftime("%m/%d")

        if df_f.empty:
            st.info(f"{futures_label} のデータがありません。")
            return

        # グラフ1: NET（ロット）推移
        st.subheader(f"{futures_label} ─ NET推移（枚）")
        fig_lots = go.Figure()
        for inv_key in selected:
            label = ALL_INVESTORS[inv_key]
            sub = df_f[df_f["investor_type"] == inv_key].sort_values("week_date")
            if sub.empty:
                continue
            inv_color = COLORS.get(label, "#aaaaaa")
            fig_lots.add_trace(go.Scatter(
                x=sub["week_label"],
                y=sub["net_lots"],
                mode="lines+markers",
                name=label,
                line=dict(color=inv_color, width=2),
                marker=dict(size=6),
                hovertemplate=f"{label}<br>%{{x}}: %{{y:,.0f}}枚<extra></extra>",
                hoverlabel=dict(bgcolor=inv_color, font=dict(color="#ffffff", size=13), bordercolor="rgba(0,0,0,0)"),
            ))
        fig_lots.update_layout(
            **plot_layout(
                xaxis=dict(title="週末日"),
                yaxis=dict(title="NET（枚）"),
                height=380,
            )
        )
        st.plotly_chart(fig_lots, use_container_width=True)

        # グラフ2: NET（億円換算）推移
        st.subheader(f"{futures_label} ─ NET推移（億円換算）")
        fig_oku = go.Figure()
        for inv_key in selected:
            label = ALL_INVESTORS[inv_key]
            sub = df_f[df_f["investor_type"] == inv_key].sort_values("week_date")
            if sub.empty or sub["net_amount_oku"].isna().all():
                continue
            vals_oku = list(sub["net_amount_oku"])
            c = INV_BAR_COLORS.get(label, {"pos": COLORS["positive"], "neg": COLORS["negative"]})
            bar_colors = [c["pos"] if v >= 0 else c["neg"] for v in vals_oku]
            fig_oku.add_trace(go.Bar(
                x=sub["week_label"],
                y=sub["net_amount_oku"],
                name=label,
                marker_color=bar_colors,
                opacity=0.9,
                hovertemplate=f"{label}<br>%{{x}}: %{{y:,.0f}}億円<extra></extra>",
                hoverlabel=dict(
                    bgcolor=[c["pos"] if v >= 0 else c["neg"] for v in vals_oku],
                    font=dict(color="#ffffff", size=13),
                    bordercolor="rgba(0,0,0,0)",
                ),
            ))
        fig_oku.update_layout(
            **plot_layout(
                barmode="group",
                xaxis=dict(title="週末日"),
                yaxis=dict(title="NET（億円）"),
                height=380,
            )
        )
        st.plotly_chart(fig_oku, use_container_width=True)

_render_futures_tab(tab_nikkei, "nikkei225_large", "日経225先物")
_render_futures_tab(tab_topix,  "topix_large",     "TOPIX先物")
