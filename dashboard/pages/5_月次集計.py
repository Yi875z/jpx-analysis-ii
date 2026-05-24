"""
月次集計ページ
- 月次フロー棒グラフ（現物・先物・合算）
- 投資家別月次ヒートマップ
- 直近12ヶ月の推移テーブル（色付きセル）
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from components.data_loader import (
    get_weekly_spot, get_weekly_futures, render_report_section_panel,
)
from components.charts import COLORS, INV_BAR_COLORS
from components.theme import render_theme_toggle, plot_layout, get_theme

st.set_page_config(
    page_title="月次集計｜JPX投資主体別売買動向ダッシュボード",
    layout="wide",
)
st.title("📅 月次集計")

# 月次レポート（あれば）から「エグゼクティブサマリー＋中期見通し」を表示
render_report_section_panel(
    ["📋 エグゼクティブサマリー"],
    "月次サマリー — 最新月AI解釈",
    report_type="monthly",
    fallback_summary=False,
)
render_report_section_panel(
    ["💡 中期見通し", "💡 戦略示唆"],
    "月次 中期見通し — AI解釈",
    report_type="monthly",
    fallback_summary=False,
)

# ─── サイドバー ───────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 表示設定")
    months_opt = st.radio("表示月数", [6, 12, 24], index=1, format_func=lambda m: f"{m}ヶ月")

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

# ─── データ取得・月次集計 ─────────────────────────────────────
weeks_needed = months_opt * 5  # 月あたり最大5週
spot_df    = get_weekly_spot(weeks=weeks_needed)
futures_df = get_weekly_futures(weeks=weeks_needed)

if spot_df.empty:
    st.info("現物データがありません。")
    st.stop()

# 月次キーを追加
for df_ in [spot_df, futures_df]:
    df_["year_month"] = pd.to_datetime(df_["week_date"]).dt.to_period("M").astype(str)

# 現物: 月次NET合計
spot_monthly = (
    spot_df[spot_df["investor_type"].isin(selected)]
    .groupby(["year_month", "investor_type"])["net_amount"]
    .sum()
    .reset_index()
    .rename(columns={"net_amount": "spot_net"})
)

# 先物: 月次NET合計（億円）
if not futures_df.empty:
    futures_monthly = (
        futures_df[
            futures_df["investor_type"].isin(selected) &
            futures_df["futures_type"].isin(["nikkei225_large", "topix_large"])
        ]
        .groupby(["year_month", "investor_type"])["net_amount_oku"]
        .sum()
        .reset_index()
        .rename(columns={"net_amount_oku": "futures_net"})
    )
else:
    futures_monthly = pd.DataFrame(columns=["year_month", "investor_type", "futures_net"])

# 合算
monthly = spot_monthly.merge(futures_monthly, on=["year_month", "investor_type"], how="left")
monthly["futures_net"] = monthly["futures_net"].fillna(0)
monthly["combined_net"] = monthly["spot_net"] + monthly["futures_net"]
monthly["inv_label"] = monthly["investor_type"].map(ALL_INVESTORS).fillna(monthly["investor_type"])

# 月順に並べ、直近N月に絞る
monthly = monthly.sort_values("year_month")
all_months = sorted(monthly["year_month"].unique())
recent_months = all_months[-months_opt:]
monthly = monthly[monthly["year_month"].isin(recent_months)]

if monthly.empty:
    st.info("月次集計データが生成できませんでした。")
    st.stop()

# ─── セクション1: 月次フロー棒グラフ ─────────────────────────
st.subheader("月次フロー（現物NET・億円）")

fig_spot = go.Figure()
for inv_key in selected:
    inv_label = ALL_INVESTORS[inv_key]
    sub = monthly[monthly["investor_type"] == inv_key]
    if sub.empty:
        continue
    c = INV_BAR_COLORS.get(inv_label, {"pos": "#aaaaaa", "neg": "#555555"})
    vals = list(sub["spot_net"])
    bar_colors_spot = [c["pos"] if v >= 0 else c["neg"] for v in vals]
    fig_spot.add_trace(go.Bar(
        name=inv_label,
        x=sub["year_month"],
        y=sub["spot_net"],
        marker_color=bar_colors_spot,
        hovertemplate=f"{inv_label}<br>%{{x}}: %{{y:,.0f}}億円<extra></extra>",
        hoverlabel=dict(
            bgcolor=[c["pos"] if v >= 0 else c["neg"] for v in vals],
            font=dict(color="#fff", size=13), bordercolor="rgba(0,0,0,0)",
        ),
    ))
fig_spot.update_layout(
    **plot_layout(
        barmode="group",
        xaxis=dict(title="年月"),
        yaxis=dict(title="NET（億円）"),
        height=360,
    )
)
st.plotly_chart(fig_spot, use_container_width=True)

st.subheader("月次フロー（現物+先物 合算NET・億円）")

fig_comb = go.Figure()
for inv_key in selected:
    inv_label = ALL_INVESTORS[inv_key]
    sub = monthly[monthly["investor_type"] == inv_key]
    if sub.empty:
        continue
    c = INV_BAR_COLORS.get(inv_label, {"pos": "#aaaaaa", "neg": "#555555"})
    vals = list(sub["combined_net"])
    bar_colors = [c["pos"] if v >= 0 else c["neg"] for v in vals]
    fig_comb.add_trace(go.Bar(
        name=inv_label,
        x=sub["year_month"],
        y=sub["combined_net"],
        marker_color=bar_colors,
        hovertemplate=f"{inv_label}<br>%{{x}}: %{{y:,.0f}}億円<extra></extra>",
        hoverlabel=dict(
            bgcolor=[c["pos"] if v >= 0 else c["neg"] for v in vals],
            font=dict(color="#fff", size=13),
            bordercolor="rgba(0,0,0,0)",
        ),
    ))
fig_comb.update_layout(
    **plot_layout(
        barmode="group",
        xaxis=dict(title="年月"),
        yaxis=dict(title="合算NET（億円）"),
        height=360,
    )
)
st.plotly_chart(fig_comb, use_container_width=True)

st.divider()

# ─── セクション2: 投資家別月次ヒートマップ ────────────────────
st.subheader("投資家別 月次NETヒートマップ（現物・億円）")

pivot_heat = monthly.pivot_table(
    index="year_month",
    columns="inv_label",
    values="spot_net",
    aggfunc="sum",
).sort_index()

z_heat = pivot_heat.values.tolist()
text_heat = [
    [f"{v:,.0f}" if pd.notna(v) else "" for v in row]
    for row in pivot_heat.values
]

fig_hm = go.Figure(go.Heatmap(
    z=z_heat,
    x=list(pivot_heat.columns),
    y=list(pivot_heat.index),
    colorscale=[[0, "#e63946"], [0.5, "#2a2a3e"], [1, "#2dc653"]],
    zmid=0,
    text=text_heat,
    texttemplate="%{text}",
    textfont=dict(size=11),
    colorbar=dict(title="NET（億円）"),
    hovertemplate="%{y} %{x}<br>%{z:,.0f}億円<extra></extra>",
    hoverlabel=dict(font=dict(color="#fff", size=13), bordercolor="rgba(0,0,0,0)"),
))
fig_hm.update_layout(
    **plot_layout(
        xaxis=dict(title="投資家"),
        yaxis=dict(title="年月", autorange="reversed"),
        height=max(300, 30 * len(pivot_heat)),
    )
)
st.plotly_chart(fig_hm, use_container_width=True)

st.divider()

# ─── セクション3: 直近12ヶ月 推移テーブル ─────────────────────
st.subheader("直近12ヶ月 推移テーブル（現物NET・億円）")

table_pivot = monthly.pivot_table(
    index="inv_label",
    columns="year_month",
    values="spot_net",
    aggfunc="sum",
).sort_index()
table_pivot.index.name = None   # "inv_label" ラベルを非表示
table_pivot.columns.name = None # "year_month" ラベルも非表示

def _color_cell(val):
    if pd.isna(val):
        return "color: #666"
    if val >= 5000:
        return "color: #2dc653; font-weight: bold"
    elif val >= 1000:
        return "color: #7ecb9b"
    elif val <= -5000:
        return "color: #e63946; font-weight: bold"
    elif val <= -1000:
        return "color: #e07070"
    else:
        return "color: #aaaaaa"

_t = get_theme()
styled = (
    table_pivot
    .style
    .format("{:,.0f}", na_rep="-")
    .map(_color_cell)
    .set_properties(**{
        "background-color": _t["bg2"],
        "border": f"1px solid {_t['border']}",
        "text-align": "right",
        "padding": "6px 10px",
    })
    .set_table_styles([{
        "selector": "th",
        "props": [("background-color", _t["bg"]), ("color", _t["subtext"]),
                  ("border", f"1px solid {_t['border']}"), ("padding", "6px 10px")],
    }])
)
st.write(styled.to_html(), unsafe_allow_html=True)
