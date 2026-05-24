"""
オプションフロー分析ページ
- 投資家別 コール/プット 買い越し枚数
- PCR (Put/Call Ratio) 推移
- 海外投資家のオプション net 時系列
- 自己（MM）のガンマ・ポジション推定
"""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from components.data_loader import (
    get_latest_week_date, get_weekly_options, render_report_section_panel,
)
from components.charts import COLORS
from components.theme import get_theme, plot_layout, render_theme_toggle

st.set_page_config(
    page_title="オプション｜JPX投資主体別売買動向ダッシュボード",
    page_icon="🎯",
    layout="wide",
)

# ─── ヘッダー ─────────────────────────────────────────────────
st.title("🎯 日経225オプション フロー")
st.caption("投資家別 コール/プット 売買差引（標準＋ミニ）と GEX 推定")

render_report_section_panel(
    ["🎯 オプション", "オプションフロー"],
    "オプションフロー — 最新週AI解釈",
)

# サイドバー
ALL_INVESTORS = {
    "foreign":          "外国人",
    "trust_bank":       "信託銀行",
    "individual":       "個人",
    "investment_trust": "投資信託",
    "corporate":        "事業法人",
    "dealer":           "自己（MM）",
}
with st.sidebar:
    st.markdown("### 表示設定")
    period = st.radio("表示期間", [8, 13, 26], index=1, format_func=lambda w: f"{w}週")
    selected = st.multiselect(
        "投資家フィルター",
        options=list(ALL_INVESTORS.keys()),
        default=["foreign", "dealer", "individual"],
        format_func=lambda k: ALL_INVESTORS[k],
    )
    st.divider()
    render_theme_toggle()
    st.divider()
    if st.button("キャッシュ更新"):
        st.cache_data.clear()
        st.rerun()

# ─── データ取得 ─────────────────────────────────────────────
df = get_weekly_options(weeks=max(period, 26))

if df.empty:
    st.warning(
        "weekly_options テーブルにデータがありません。\n"
        "`python scripts/backfill_options.py` を実行して取得してください。"
    )
    st.stop()

df["week_date"] = pd.to_datetime(df["week_date"])
latest = df["week_date"].max()

# 標準＋ミニ合算ヘルパー
def _agg_call_put(sub: pd.DataFrame) -> pd.DataFrame:
    """option_type を call/put に集約"""
    sub = sub.copy()
    sub["side"] = sub["option_type"].apply(
        lambda x: "call" if "call" in x else "put"
    )
    return (sub.groupby(["week_date", "investor_type", "side"])
              ["net_lots"].sum().reset_index())

# ─── KPI: 最新週の海外勢 PCR ────────────────────────────────
latest_df = df[df["week_date"] == latest]
agg = _agg_call_put(latest_df)
foreign_agg = agg[agg["investor_type"] == "foreign"]
foreign_call = float(foreign_agg[foreign_agg["side"] == "call"]["net_lots"].sum() or 0)
foreign_put  = float(foreign_agg[foreign_agg["side"] == "put"]["net_lots"].sum() or 0)
pcr = (foreign_put / foreign_call) if foreign_call > 0 else None

dealer_agg = agg[agg["investor_type"] == "dealer"]
dealer_call = float(dealer_agg[dealer_agg["side"] == "call"]["net_lots"].sum() or 0)
dealer_put  = float(dealer_agg[dealer_agg["side"] == "put"]["net_lots"].sum() or 0)

# MM ガンマ判定（コール・プット両方 net 売り越し → -GEX）
gex_label, gex_color = "-", "#888888"
if dealer_call < 0 and dealer_put < 0:
    gex_label, gex_color = "-GEX (ボラ拡大)", "#e63946"
elif dealer_call > 0 and dealer_put > 0:
    gex_label, gex_color = "+GEX (Pinning)", "#2dc653"
else:
    gex_label, gex_color = "中立", "#f5a623"

t = get_theme()
st.markdown(f"### 最新週: {latest.strftime('%Y-%m-%d')}")

k1, k2, k3, k4 = st.columns(4)
def _kpi_card(col, title: str, value: str, sub: str, color: str):
    with col:
        st.markdown(
            f"""<div style="background:{t['bg2']};border-radius:8px;padding:14px 18px;border-left:4px solid {color}">
              <div style="color:{t['subtext']};font-size:12px;margin-bottom:4px">{title}</div>
              <div style="font-size:24px;font-weight:bold;color:{color}">{value}</div>
              <div style="color:{t['subtext']};font-size:12px;margin-top:4px">{sub}</div>
            </div>""", unsafe_allow_html=True
        )
pcr_color = "#e63946" if (pcr is not None and pcr > 1.5) else "#2dc653" if (pcr is not None and pcr < 0.7) else "#f5a623"
_kpi_card(k1, "海外 PCR（プット/コール）", f"{pcr:.2f}" if pcr is not None else "—",
          "1.5+ = ヘッジ強・弱気バイアス", pcr_color)
_kpi_card(k2, "海外プット net 枚数", f"{int(foreign_put):+,}", "正=買い越し（下方ヘッジ）", "#1a6b9e")
_kpi_card(k3, "海外コール net 枚数", f"{int(foreign_call):+,}", "正=買い越し（上方期待）", "#2dc653")
_kpi_card(k4, "MM ガンマ推定", gex_label, "自己コール・プット net から推定", gex_color)

st.divider()

# ─── 投資家別 コール/プット 棒グラフ（最新週） ─────────────────
st.subheader("最新週: 投資家別 コール/プット 売買差引（net 枚数）")
plot_df = agg[agg["investor_type"].isin(selected)].copy()
plot_df["inv_label"] = plot_df["investor_type"].map(ALL_INVESTORS)

fig_bar = go.Figure()
for side, color in [("call", "#2dc653"), ("put", "#e63946")]:
    sub = plot_df[plot_df["side"] == side]
    fig_bar.add_trace(go.Bar(
        name="コール" if side == "call" else "プット",
        x=sub["inv_label"],
        y=sub["net_lots"],
        marker_color=color,
        hovertemplate=("コール" if side == "call" else "プット") +
                      "<br>%{x}: %{y:+,}枚<extra></extra>",
        opacity=0.85,
    ))
fig_bar.update_layout(barmode="group", **plot_layout(
    xaxis=dict(title="投資家"),
    yaxis=dict(title="net 枚数（買い越し=正）"),
    height=380,
))
st.plotly_chart(fig_bar, use_container_width=True)

st.divider()

# ─── PCR 時系列 ───────────────────────────────────────────
st.subheader(f"海外投資家 PCR（プット/コール比）の推移（直近{period}週）")
cutoff = pd.Timestamp.today() - pd.DateOffset(weeks=period)
all_agg = _agg_call_put(df[df["week_date"] >= cutoff])
f_agg = all_agg[all_agg["investor_type"] == "foreign"]
pivot = f_agg.pivot(index="week_date", columns="side", values="net_lots").fillna(0)
if not pivot.empty and "call" in pivot.columns and "put" in pivot.columns:
    pivot["pcr"] = pivot.apply(
        lambda r: (r["put"] / r["call"]) if r["call"] > 0 else None, axis=1
    )
    pivot = pivot.reset_index()
    pivot["label"] = pivot["week_date"].dt.strftime("%m/%d")
    fig_pcr = go.Figure()
    fig_pcr.add_trace(go.Scatter(
        x=pivot["label"], y=pivot["pcr"],
        mode="lines+markers", name="PCR",
        line=dict(color="#1a6b9e", width=2.5), marker=dict(size=7),
        hovertemplate="PCR %{x}: %{y:.2f}<extra></extra>",
    ))
    fig_pcr.add_hline(y=1.0, line=dict(color="#888", width=1, dash="dot"),
                      annotation_text="PCR=1.0", annotation_font_color="#888")
    fig_pcr.add_hline(y=1.5, line=dict(color="#e63946", width=1, dash="dash"),
                      annotation_text="ヘッジ強（1.5+）", annotation_font_color="#e63946")
    fig_pcr.update_layout(**plot_layout(
        xaxis=dict(title="週末日"),
        yaxis=dict(title="PCR (プット net / コール net)"),
        height=340,
    ))
    st.plotly_chart(fig_pcr, use_container_width=True)
else:
    st.caption("データ不足のため PCR を計算できません。")

st.divider()

# ─── 海外投資家の4オプション net 時系列 ───────────────────
st.subheader(f"海外投資家 オプション net 時系列（直近{period}週）")
f_df = df[(df["investor_type"] == "foreign") & (df["week_date"] >= cutoff)].copy()
f_df["label"] = f_df["week_date"].dt.strftime("%m/%d")
fig_ts = go.Figure()
OPT_COLORS = {
    "nikkei225_call":      "#2dc653",
    "nikkei225_put":       "#e63946",
    "nikkei225_mini_call": "#a8d8b9",
    "nikkei225_mini_put":  "#f5a8b0",
}
OPT_JP = {
    "nikkei225_call":      "日経225 コール",
    "nikkei225_put":       "日経225 プット",
    "nikkei225_mini_call": "ミニ コール",
    "nikkei225_mini_put":  "ミニ プット",
}
for ot, color in OPT_COLORS.items():
    sub = f_df[f_df["option_type"] == ot].sort_values("week_date")
    if sub.empty:
        continue
    fig_ts.add_trace(go.Scatter(
        x=sub["label"], y=sub["net_lots"],
        mode="lines+markers", name=OPT_JP[ot],
        line=dict(color=color, width=2), marker=dict(size=6),
        hovertemplate=f"{OPT_JP[ot]}<br>%{{x}}: %{{y:+,}}枚<extra></extra>",
    ))
fig_ts.update_layout(**plot_layout(
    xaxis=dict(title="週末日"),
    yaxis=dict(title="net 枚数（買い越し=正）"),
    height=380,
))
st.plotly_chart(fig_ts, use_container_width=True)

st.divider()

# ─── データテーブル ──────────────────────────────────────
with st.expander("📊 直近週の詳細データ（全投資家・全 option_type）"):
    show = latest_df.copy()
    show["option_type"] = show["option_type"].map({
        "nikkei225_call": "日経225 コール",
        "nikkei225_put":  "日経225 プット",
        "nikkei225_mini_call": "ミニ コール",
        "nikkei225_mini_put":  "ミニ プット",
    })
    show["投資家"] = show["investor_type"].map(ALL_INVESTORS).fillna(show["investor_type"])
    show = show[["投資家", "option_type", "long_lots", "short_lots", "net_lots", "net_amount_oku"]]
    show.columns = ["投資家", "種別", "買 (枚)", "売 (枚)", "net (枚)", "net (億円)"]
    st.dataframe(show, use_container_width=True, hide_index=True)
