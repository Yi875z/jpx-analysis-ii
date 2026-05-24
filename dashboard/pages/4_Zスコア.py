"""
Zスコア分析ページ
weekly_spot / weekly_futures から動的にZスコア・移動平均を計算
- 投資家×週 ヒートマップ（±2.0閾値）
- 26週 vs 52週 Zスコア比較
- 4週移動平均トレンド
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from components.data_loader import (
    get_weekly_spot, get_weekly_futures, render_report_section_panel,
)
from components.charts import COLORS
from components.theme import render_theme_toggle, plot_layout

st.set_page_config(
    page_title="Zスコア｜JPX投資主体別売買動向ダッシュボード",
    layout="wide",
)
st.title("📊 Zスコア分析")

render_report_section_panel(
    ["📅 先週比・Zスコア", "Zスコア分析"],
    "Zスコア — 最新週AI解釈",
)

# ─── サイドバー ───────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 表示設定")
    period = st.radio("表示期間", [13, 26, 52], index=1, format_func=lambda w: f"{w}週")
    data_type = st.radio(
        "データ種別", ["spot", "futures"],
        format_func=lambda x: "現物" if x == "spot" else "先物（億円換算）"
    )
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

# ─── データ取得・Zスコア動的計算 ─────────────────────────────
# Zスコア計算には最低52週の履歴が必要なため、常に全データを取得
@st.cache_data(ttl=3600)
def _compute_zscores(data_type: str) -> pd.DataFrame:
    """週次NETデータからZスコア・移動平均を動的計算"""
    if data_type == "spot":
        raw = get_weekly_spot(weeks=104)
        if raw.empty:
            return pd.DataFrame()
        raw = raw[["week_date", "investor_type", "net_amount"]].copy()
        raw.rename(columns={"net_amount": "value"}, inplace=True)
    else:
        raw = get_weekly_futures(weeks=104)
        if raw.empty:
            return pd.DataFrame()
        raw = raw[
            raw["futures_type"].isin(["nikkei225_large", "topix_large"])
        ].groupby(["week_date", "investor_type"])["net_amount_oku"].sum().reset_index()
        raw.rename(columns={"net_amount_oku": "value"}, inplace=True)

    raw["week_date"] = pd.to_datetime(raw["week_date"])

    rows = []
    for inv_type, grp in raw.groupby("investor_type"):
        grp = grp.sort_values("week_date").copy()
        grp["ma4w"]      = grp["value"].rolling(4, min_periods=2).mean()
        grp["zscore_26w"] = (
            (grp["value"] - grp["value"].rolling(26, min_periods=10).mean())
            / grp["value"].rolling(26, min_periods=10).std()
        )
        grp["zscore_52w"] = (
            (grp["value"] - grp["value"].rolling(52, min_periods=10).mean())
            / grp["value"].rolling(52, min_periods=10).std()
        )
        rows.append(grp)

    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()

with st.spinner("Zスコアを計算中..."):
    df_all = _compute_zscores(data_type)

if df_all.empty:
    st.info("データがありません。")
    st.stop()

# 表示期間で絞り込み
cutoff = pd.Timestamp.today() - pd.DateOffset(weeks=period)
df = df_all[
    (df_all["week_date"] >= cutoff) &
    (df_all["investor_type"].isin(selected))
].copy()
df["week_label"] = df["week_date"].dt.strftime("%m/%d")
df["inv_label"]  = df["investor_type"].map(ALL_INVESTORS).fillna(df["investor_type"])

if df.empty:
    st.info("選択した条件のデータがありません。")
    st.stop()

type_label = "現物" if data_type == "spot" else "先物"

# ─── セクション1: Zスコア ヒートマップ ────────────────────────
st.subheader(f"Zスコア ヒートマップ（{type_label}・26週基準）")
st.caption("🔴 +2.0以上=過熱  🔵 -2.0以下=売られすぎ  ⬜ ±1.0以内=中立")

pivot = df.pivot_table(
    index="week_date",
    columns="inv_label",
    values="zscore_26w",
    aggfunc="first",
).sort_index()
pivot.index = pivot.index.strftime("%m/%d")

colorscale = [
    [0.0,  "#1a6b9e"],
    [0.33, "#4a9abe"],
    [0.45, "#3a3a4e"],
    [0.5,  "#2a2a3e"],
    [0.55, "#4e3a3a"],
    [0.67, "#c0534a"],
    [1.0,  "#e63946"],
]
text_vals = [
    [f"{v:.2f}" if pd.notna(v) else "" for v in row]
    for row in pivot.values
]

fig_heat = go.Figure(go.Heatmap(
    z=pivot.values.tolist(),
    x=list(pivot.columns),
    y=list(pivot.index),
    colorscale=colorscale,
    zmid=0, zmin=-3, zmax=3,
    text=text_vals,
    texttemplate="%{text}",
    textfont=dict(size=11),
    colorbar=dict(title="Zスコア", tickvals=[-3,-2,-1,0,1,2,3]),
    hovertemplate="%{y} %{x}<br>Zスコア: %{z:.2f}<extra></extra>",
    hoverlabel=dict(font=dict(color="#ffffff", size=13), bordercolor="rgba(0,0,0,0)"),
))
fig_heat.update_layout(
    **plot_layout(
        xaxis=dict(title="投資家"),
        yaxis=dict(title="週末日", autorange="reversed"),
        height=max(350, 22 * len(pivot)),
    )
)
st.plotly_chart(fig_heat, use_container_width=True)

st.divider()

# ─── セクション2: 26週 vs 52週 Zスコア比較 ───────────────────
st.subheader(f"26週 vs 52週 Zスコア比較（{type_label}）")

tabs = st.tabs([ALL_INVESTORS.get(k, k) for k in selected])
for tab, inv_key in zip(tabs, selected):
    inv_label = ALL_INVESTORS.get(inv_key, inv_key)
    with tab:
        sub = df[df["investor_type"] == inv_key].sort_values("week_date")
        if sub.empty:
            st.info("データがありません。")
            continue

        color = COLORS.get(inv_label, "#00b4d8")
        fig_z = go.Figure()
        fig_z.add_trace(go.Scatter(
            x=sub["week_label"], y=sub["zscore_26w"],
            mode="lines+markers", name="26週Zスコア",
            line=dict(color=color, width=2), marker=dict(size=5),
            hovertemplate="26週Z %{x}: %{y:.2f}<extra></extra>",
            hoverlabel=dict(bgcolor=color, font=dict(color="#fff", size=13), bordercolor="rgba(0,0,0,0)"),
        ))
        fig_z.add_trace(go.Scatter(
            x=sub["week_label"], y=sub["zscore_52w"],
            mode="lines+markers", name="52週Zスコア",
            line=dict(color="#f77f00", width=2, dash="dot"), marker=dict(size=5),
            hovertemplate="52週Z %{x}: %{y:.2f}<extra></extra>",
            hoverlabel=dict(bgcolor="#f77f00", font=dict(color="#fff", size=13), bordercolor="rgba(0,0,0,0)"),
        ))
        for y_val, col, label in [(2,"#e63946","+2.0"),(-2,"#1a6b9e","-2.0"),(1,"#555","+1.0"),(-1,"#555","-1.0")]:
            fig_z.add_hline(y=y_val, line=dict(color=col, width=1, dash="dash"),
                            annotation_text=label, annotation_font_color=col)
        fig_z.update_layout(
            **plot_layout(
                xaxis=dict(title="週末日"),
                yaxis=dict(title="Zスコア"),
                height=360,
            )
        )
        st.plotly_chart(fig_z, use_container_width=True)

st.divider()

# ─── セクション3: 4週移動平均トレンド ────────────────────────
st.subheader(f"4週移動平均トレンド（{type_label}・億円）")

fig_ma = go.Figure()
for inv_key in selected:
    inv_label = ALL_INVESTORS.get(inv_key, inv_key)
    sub = df[df["investor_type"] == inv_key].sort_values("week_date")
    if sub.empty or sub["ma4w"].isna().all():
        continue
    color = COLORS.get(inv_label, "#aaaaaa")
    fig_ma.add_trace(go.Scatter(
        x=sub["week_label"], y=sub["ma4w"],
        mode="lines+markers", name=inv_label,
        line=dict(color=color, width=2), marker=dict(size=5),
        hovertemplate=f"{inv_label} %{{x}}: %{{y:,.0f}}億円<extra></extra>",
        hoverlabel=dict(bgcolor=color, font=dict(color="#fff", size=13), bordercolor="rgba(0,0,0,0)"),
    ))
fig_ma.update_layout(
    **plot_layout(
        xaxis=dict(title="週末日"),
        yaxis=dict(title="4週MA（億円）"),
        height=380,
    )
)
st.plotly_chart(fig_ma, use_container_width=True)
