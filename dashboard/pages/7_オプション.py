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
    "foreign":          "海外投資家",
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

# ラージ（指数×1,000円）/ ミニ（×100円, 1/10・個人向け）の商品コード
_LARGE = ("nikkei225_call", "nikkei225_put")
_MINI  = ("nikkei225_mini_call", "nikkei225_mini_put")


# 標準＋ミニ合算ヘルパー（net_lots と net_amount_oku の両方を集約）
def _agg_call_put(sub: pd.DataFrame) -> pd.DataFrame:
    """option_type を call/put に集約"""
    sub = sub.copy()
    sub["side"] = sub["option_type"].apply(
        lambda x: "call" if "call" in x else "put"
    )
    return (sub.groupby(["week_date", "investor_type", "side"])
              [["net_lots", "net_amount_oku"]].sum().reset_index())

# ─── KPI: 最新週の海外勢 PCR（ラージのみ・機関フローを正しく反映） ──────────
latest_df = df[df["week_date"] == latest]
agg = _agg_call_put(latest_df)                                              # 全商品（棒グラフ用）
agg_large = _agg_call_put(latest_df[latest_df["option_type"].isin(_LARGE)])  # ラージのみ（PCR/KPI/GEX用）
foreign_agg = agg_large[agg_large["investor_type"] == "foreign"]
foreign_call = float(foreign_agg[foreign_agg["side"] == "call"]["net_lots"].sum() or 0)
foreign_put  = float(foreign_agg[foreign_agg["side"] == "put"]["net_lots"].sum() or 0)
pcr = (foreign_put / foreign_call) if foreign_call > 0 else None

dealer_agg = agg_large[agg_large["investor_type"] == "dealer"]
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
_kpi_card(k1, "海外 PCR（プット/コール・ラージ）", f"{pcr:.2f}" if pcr is not None else "—",
          "1.5+ = ヘッジ強・弱気バイアス", pcr_color)
_kpi_card(k2, "海外プット net 枚数（ラージ）", f"{int(foreign_put):+,}", "正=買い越し（下方ヘッジ）", "#1a6b9e")
_kpi_card(k3, "海外コール net 枚数（ラージ）", f"{int(foreign_call):+,}", "正=買い越し（上方期待）", "#2dc653")
_kpi_card(k4, "MM ガンマ推定（ラージ）", gex_label, "自己コール・プット net から推定", gex_color)

st.divider()

# ─── 投資家別 コール/プット 棒グラフ（最新週・金額建て） ─────────────────
st.subheader("最新週: 投資家別 コール/プット 売買差引（net 億円）")
st.caption("ラージ＋ミニを net 金額（億円）で合算。金額建てなので大小オプションを公平に比較できる。")
plot_df = agg[agg["investor_type"].isin(selected)].copy()
plot_df["inv_label"] = plot_df["investor_type"].map(ALL_INVESTORS)

fig_bar = go.Figure()
for side, color in [("call", "#2dc653"), ("put", "#e63946")]:
    sub = plot_df[plot_df["side"] == side]
    fig_bar.add_trace(go.Bar(
        name="コール" if side == "call" else "プット",
        x=sub["inv_label"],
        y=sub["net_amount_oku"],
        marker_color=color,
        hovertemplate=("コール" if side == "call" else "プット") +
                      "<br>%{x}: %{y:+,.1f}億円<extra></extra>",
        opacity=0.85,
    ))
fig_bar.update_layout(barmode="group", **plot_layout(
    xaxis=dict(title="投資家"),
    yaxis=dict(title="net 金額（億円, 買い越し=正）"),
    height=380,
))
st.plotly_chart(fig_bar, use_container_width=True)

st.divider()

# ─── PCR 時系列 ───────────────────────────────────────────
st.subheader(f"海外投資家 PCR（プット/コール比・ラージ）の推移（直近{period}週）")
cutoff = pd.Timestamp.today() - pd.DateOffset(weeks=period)
all_agg = _agg_call_put(df[(df["week_date"] >= cutoff) & (df["option_type"].isin(_LARGE))])
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

# ─── 海外投資家 日経225ラージ・オプション net 時系列（金額・億円） ──────────
# ラージ（指数×1,000円）とミニ（×100円, 1/10）は単位も参加者層も異なる。
# 海外勢の機関フローはラージに出るため、ラージのみ・net金額(億円)で表示して
# 枚数混在による歪みを排除する。ミニ(個人向け)は下の構成比セクションで扱う。
st.subheader(f"海外投資家 日経225オプション（ラージ）net 時系列・金額建て（直近{period}週）")
st.caption(
    "海外勢の本気のポジションはラージ（指数×1,000円）に表れる。ミニ（×100円・個人向け）は"
    "経済的価値が1/10で枚数比較が歪むためここでは除外し、net 金額（億円）で表示。"
    "プット買い越し＝下方ヘッジ／弱気、コール買い越し＝上方期待／強気。"
)
LARGE_JP = {"nikkei225_call": "日経225 コール", "nikkei225_put": "日経225 プット"}
LARGE_COLORS = {"nikkei225_call": "#2dc653", "nikkei225_put": "#e63946"}
f_df = df[(df["investor_type"] == "foreign") & (df["week_date"] >= cutoff)].copy()
f_df["label"] = f_df["week_date"].dt.strftime("%m/%d")
fig_ts = go.Figure()
for ot, jp in LARGE_JP.items():
    sub = f_df[f_df["option_type"] == ot].sort_values("week_date")
    if sub.empty:
        continue
    fig_ts.add_trace(go.Scatter(
        x=sub["label"], y=sub["net_amount_oku"],
        mode="lines+markers", name=jp,
        line=dict(color=LARGE_COLORS[ot], width=2.5), marker=dict(size=6),
        hovertemplate=f"{jp}<br>%{{x}}: %{{y:+,.1f}}億円<extra></extra>",
    ))
fig_ts.update_layout(**plot_layout(
    xaxis=dict(title="週末日"),
    yaxis=dict(title="net 金額（億円, 買い越し=正）"),
    height=380,
))
st.plotly_chart(fig_ts, use_container_width=True)

st.divider()

# ─── データテーブル ──────────────────────────────────────
# 投資家11区分・オプション商品8種すべての日本語ラベル（未対応をNaN/英語のまま出さない）
INVESTOR_JP_FULL = {
    "dealer":             "自己（MM）",
    "insurance":          "生損保",
    "city_regional_bank": "都銀・地銀",
    "trust_bank":         "信託銀行",
    "other_financial":    "その他金融機関",
    "investment_trust":   "投資信託",
    "corporate":          "事業法人",
    "other_institution":  "その他法人",
    "securities":         "証券会社",
    "individual":         "個人",
    "foreign":            "海外投資家",
}
OPT_TYPE_JP = {
    "nikkei225_call":      "日経225 コール",
    "nikkei225_put":       "日経225 プット",
    "nikkei225_mini_call": "日経225ミニ コール",
    "nikkei225_mini_put":  "日経225ミニ プット",
    "topix_call":          "TOPIX コール",
    "topix_put":           "TOPIX プット",
    "jpx400_call":         "JPX400 コール",
    "jpx400_put":          "JPX400 プット",
}

with st.expander("📊 直近週の詳細データ（建玉のある投資家・商品のみ）"):
    show = latest_df.copy()
    # 売買が全くゼロの行（建玉なし）は除外して見やすくする
    show = show[(show["long_lots"] != 0) | (show["short_lots"] != 0) | (show["net_lots"] != 0)]
    # ネット金額の絶対値が大きい順（注目すべきフローを上に）
    show = show.sort_values("net_amount_oku", key=lambda s: s.abs(), ascending=False)
    show["投資家"] = show["investor_type"].map(INVESTOR_JP_FULL).fillna(show["investor_type"])
    show["商品"]   = show["option_type"].map(OPT_TYPE_JP).fillna(show["option_type"])

    disp = show[["投資家", "商品", "long_lots", "short_lots", "net_lots", "net_amount_oku"]].copy()
    disp.columns = ["投資家", "商品", "買 (枚)", "売 (枚)", "ネット (枚)", "ネット (億円)"]
    for c in ["買 (枚)", "売 (枚)", "ネット (枚)"]:
        disp[c] = disp[c].map(lambda v: f"{int(v):,}")
    disp["ネット (億円)"] = disp["ネット (億円)"].map(lambda v: f"{v:,.2f}")

    if disp.empty:
        st.caption("直近週は建玉のある投資家・商品がありません。")
    else:
        # st.dataframe(対話型グリッド)はcanvas描画でconfig.tomlのテーマにしか従わず、
        # 実行時のダーク/ライト切替に追従しない。HTMLテーブルにして theme.py のCSSで両モード対応する。
        st.markdown(
            f'<div style="overflow-x:auto">{disp.to_html(index=False, border=0, justify="center")}</div>',
            unsafe_allow_html=True,
        )

st.divider()

# ─── ラージ vs ミニ：投資部門の構成比（誰がその市場を動かしているか） ──────────
# 「ミニ＝個人向け／ラージ＝機関」という通説を、JPX投資部門別データ自体で検証する。
st.subheader(f"ラージ vs ミニ：投資部門の構成比（直近{period}週・売買高ベース）")
st.caption(
    "各市場の総売買高（買＋売 枚数）に占める投資家区分のシェア。"
    "ミニ（2023年上場・個人向け設計）で個人の比率が高く、ラージで海外・自己（機関）の比率が"
    "高いほど「ミニ＝個人／ラージ＝機関」の通説と整合する。枚数の大小は%化で打ち消されるため公平に比較できる。"
)
comp_src = df[df["week_date"] >= cutoff].copy()
comp_src["市場"] = comp_src["option_type"].apply(
    lambda x: "ラージ" if x in _LARGE else ("ミニ" if x in _MINI else None)
)
comp_src = comp_src[comp_src["市場"].notna()].copy()
comp_src["vol"] = comp_src["long_lots"].abs() + comp_src["short_lots"].abs()
comp_src["投資家"] = comp_src["investor_type"].map(INVESTOR_JP_FULL).fillna(comp_src["investor_type"])

if comp_src.empty or comp_src["vol"].sum() == 0:
    st.caption("構成比を計算できるデータがありません。")
else:
    pivot = comp_src.groupby(["市場", "投資家"], as_index=False)["vol"].sum()
    pivot["share"] = pivot.groupby("市場")["vol"].transform(lambda s: s / s.sum() * 100)
    # 投資家の並び順はラージのシェア降順で固定（左右の比較をしやすく）
    order = (pivot[pivot["市場"] == "ラージ"].sort_values("share")["投資家"].tolist()
             or pivot["投資家"].drop_duplicates().tolist())
    fig_comp = go.Figure()
    for mkt, color in [("ラージ", "#29b6f6"), ("ミニ", "#f5a8b0")]:
        sub = pivot[pivot["市場"] == mkt].set_index("投資家").reindex(order).reset_index()
        fig_comp.add_trace(go.Bar(
            y=sub["投資家"], x=sub["share"], name=mkt, orientation="h",
            marker_color=color, opacity=0.85,
            hovertemplate=f"{mkt}　%{{y}}: %{{x:.1f}}%<extra></extra>",
        ))
    fig_comp.update_layout(barmode="group", **plot_layout(
        xaxis=dict(title="構成比（%）"),
        yaxis=dict(title=""),
        height=460,
    ))
    st.plotly_chart(fig_comp, use_container_width=True)
