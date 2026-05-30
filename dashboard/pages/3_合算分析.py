"""
合算分析ページ
- 現物 vs 先物 方向一致/乖離チャート（2軸）
- ツインエンジン発動履歴（ヒートマップ）
- 海外投資家 現物+先物合算 累積フロー（棒+折れ線）
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from components.data_loader import get_weekly_combined, render_report_section_panel
from components.charts import COLORS
from components.theme import render_theme_toggle, plot_layout, get_theme

st.set_page_config(page_title="合算分析｜JPX投資主体別売買動向ダッシュボード", layout="wide")
st.title("⚡ 合算分析")

render_report_section_panel(
    ["🔢 合算", "合算（現物"],
    "合算分析 — 最新週AI解釈",
)

# ─── サイドバー ───────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 表示設定")
    period = st.radio("表示期間", [13, 26, 52], index=1, format_func=lambda w: f"{w}週")
    st.divider()
    render_theme_toggle()
    st.divider()
    if st.button("キャッシュ更新"):
        st.cache_data.clear()
        st.rerun()

# ─── データ取得 ────────────────────────────────────────────────
df = get_weekly_combined(weeks=period)

if df.empty:
    st.info("データがありません。まずデータ取得スクリプトを実行してください。")
    st.stop()

df["week_date"] = pd.to_datetime(df["week_date"])
df["week_label"] = df["week_date"].dt.strftime("%m/%d")

# ─── セクション1: 現物 vs 先物 方向一致/乖離チャート ──────────
st.subheader("海外投資家：現物 vs 先物 方向一致 / 乖離チャート")

foreign = df[df["investor_type"] == "foreign"].sort_values("week_date")
if foreign.empty:
    st.info("海外投資家データがありません。")
else:
    fig_dual = go.Figure()
    # 現物NET（棒グラフ）
    spot_vals = list(foreign["spot_net"])
    spot_colors = [COLORS["positive"] if v >= 0 else COLORS["negative"] for v in spot_vals]
    fig_dual.add_trace(go.Bar(
        name="現物NET",
        x=foreign["week_label"],
        y=foreign["spot_net"],
        marker_color=spot_colors,
        opacity=0.7,
        yaxis="y1",
        hovertemplate="現物NET<br>%{x}: %{y:,.0f}億円<extra></extra>",
        hoverlabel=dict(
            bgcolor=[COLORS["positive"] if v >= 0 else COLORS["negative"] for v in spot_vals],
            font=dict(color="#ffffff", size=13),
            bordercolor="rgba(0,0,0,0)",
        ),
    ))
    # 先物NET（折れ線、第2軸）
    fig_dual.add_trace(go.Scatter(
        name="先物NET",
        x=foreign["week_label"],
        y=foreign["futures_net_oku"],
        mode="lines+markers",
        line=dict(color=COLORS.get("海外投資家", "#29b6f6"), width=2, dash="dot"),
        marker=dict(size=5),
        yaxis="y2",
        hovertemplate="先物NET<br>%{x}: %{y:,.0f}億円<extra></extra>",
        hoverlabel=dict(bgcolor=COLORS.get("海外投資家", "#29b6f6"), font=dict(color="#ffffff", size=13), bordercolor="rgba(0,0,0,0)"),
    ))
    _t = get_theme()
    fig_dual.update_layout(
        **plot_layout(
            xaxis=dict(title="週末日"),
            yaxis=dict(title="現物NET（億円）"),
            yaxis2=dict(title="先物NET（億円）", overlaying="y", side="right", gridcolor=_t["grid"]),
            height=400,
            barmode="overlay",
        )
    )
    st.plotly_chart(fig_dual, use_container_width=True)

st.divider()

# ─── セクション2: ツインエンジン発動履歴（ヒートマップ） ────────
st.subheader("ツインエンジン発動履歴")
st.caption(
    "**ツインエンジン発動の定義:** 同一週に「現物NET買い越し」かつ「先物NET買い越し（億円換算）」が"
    "同時に成立した状態。現物・先物の両面から資金が流入しており、需給面での強い買い圧力を示す強気シグナル。"
    "※ 投資信託は先物取引を行わないため除外。"
)

twin_df = df[["week_date", "investor_type", "is_twin_engine"]].copy()
twin_df = twin_df[twin_df["is_twin_engine"].notna()]
twin_df = twin_df[twin_df["investor_type"] != "inv_trust"]  # 先物非取引のため除外

if twin_df.empty:
    st.info("ツインエンジンデータがありません。")
else:
    # 週×投資家のピボットテーブルを作り、1=ON / 0=OFF でヒートマップ
    twin_pivot = twin_df.pivot_table(
        index="week_date",
        columns="investor_type",
        values="is_twin_engine",
        aggfunc="max",
    ).sort_index()

    # カラム名を日本語に変換
    inv_ja = {"foreign": "海外投資家", "trust_bank": "信託銀行", "inv_trust": "投資信託",
              "individual": "個人", "corporate": "事業法人", "dealer": "自己"}
    twin_pivot.columns = [inv_ja.get(c, c) for c in twin_pivot.columns]
    twin_pivot.index = twin_pivot.index.strftime("%m/%d")
    twin_values = twin_pivot.fillna(0).astype(int).values.tolist()

    _t2 = get_theme()
    off_color = _t2["border"]  # ライト=#cccccc / ダーク=#333333（OFFセルを薄く可視化）
    fig_heat = go.Figure(go.Heatmap(
        z=twin_values,
        x=list(twin_pivot.columns),
        y=list(twin_pivot.index),
        colorscale=[[0, off_color], [1, "#2dc653"]],
        showscale=False,
        text=[[("ON" if v else "") for v in row] for row in twin_values],
        texttemplate="%{text}",
        hovertemplate="%{y} %{x}: %{z}<extra></extra>",
    ))
    fig_heat.update_layout(
        **plot_layout(
            xaxis=dict(title="投資家"),
            yaxis=dict(title="週末日", autorange="reversed"),
            height=max(300, 20 * len(twin_pivot)),
        )
    )
    st.plotly_chart(fig_heat, use_container_width=True)

st.divider()

# ─── セクション3: 海外投資家 累積フロー（棒+折れ線複合） ─────────
st.subheader("海外投資家 現物+先物合算 累積フロー（億円）")

if foreign.empty:
    st.info("海外投資家データがありません。")
else:
    foreign = foreign.copy()
    foreign["cumulative_net"] = foreign["combined_net"].cumsum()

    cum_vals = list(foreign["combined_net"])
    bar_colors = [COLORS["positive"] if v >= 0 else COLORS["negative"] for v in cum_vals]
    fig_cum = go.Figure()
    fig_cum.add_trace(go.Bar(
        name="週次合算NET",
        x=foreign["week_label"],
        y=foreign["combined_net"],
        marker_color=bar_colors,
        opacity=0.75,
        hovertemplate="週次NET<br>%{x}: %{y:,.0f}億円<extra></extra>",
        hoverlabel=dict(
            bgcolor=[COLORS["positive"] if v >= 0 else COLORS["negative"] for v in cum_vals],
            font=dict(color="#ffffff", size=13),
            bordercolor="rgba(0,0,0,0)",
        ),
    ))
    fig_cum.add_trace(go.Scatter(
        name="累積フロー",
        x=foreign["week_label"],
        y=foreign["cumulative_net"],
        mode="lines+markers",
        line=dict(color=COLORS.get("海外投資家", "#29b6f6"), width=2),
        marker=dict(size=5),
        yaxis="y2",
        hovertemplate="累積NET<br>%{x}: %{y:,.0f}億円<extra></extra>",
        hoverlabel=dict(bgcolor=COLORS.get("海外投資家", "#29b6f6"), font=dict(color="#ffffff", size=13), bordercolor="rgba(0,0,0,0)"),
    ))
    fig_cum.update_layout(
        **plot_layout(
            xaxis=dict(title="週末日"),
            yaxis=dict(title="週次NET（億円）"),
            yaxis2=dict(title="累積フロー（億円）", overlaying="y", side="right", gridcolor=_t["grid"]),
            height=400,
        )
    )
    st.plotly_chart(fig_cum, use_container_width=True)
