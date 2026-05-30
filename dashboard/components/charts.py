"""
グラフ共通関数
Plotly図表の生成ユーティリティ
"""
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

COLORS = {
    "海外投資家":   "#29b6f6",  # sky blue
    "信託銀行": "#ffa726",  # amber
    "個人":     "#ef5350",  # red
    "事業法人": "#66bb6a",  # green
    "自己":     "#ce93d8",  # lavender
    "positive": "#2dc653",
    "negative": "#e63946",
}

# バーチャート専用: 投資家別 買い越し（明）/ 売り越し（暗）カラーペア
# 5色を hue で完全分離: 青 / 橙 / 赤 / 緑 / 紫
INV_BAR_COLORS = {
    "海外投資家":   {"pos": "#29b6f6", "neg": "#0277bd"},   # sky blue / dark blue
    "信託銀行": {"pos": "#ffa726", "neg": "#bf360c"},   # amber / burnt orange
    "個人":     {"pos": "#ef5350", "neg": "#b71c1c"},   # red / dark red
    "事業法人": {"pos": "#66bb6a", "neg": "#1b5e20"},   # light green / dark green
    "自己":     {"pos": "#ce93d8", "neg": "#6a1b9a"},   # lavender / dark purple
}

INVESTOR_LABEL = {
    "foreign":    "海外投資家",
    "trust_bank": "信託銀行",
    "inv_trust":  "投資信託",
    "individual": "個人",
    "corporate":  "事業法人",
    "dealer":     "自己",
}


def _label(investor_type: str) -> str:
    return INVESTOR_LABEL.get(investor_type, investor_type)


def _hover_pn(values) -> dict:
    """正負で背景色を変えるhoverlabel設定"""
    return dict(
        bgcolor=[COLORS["positive"] if v >= 0 else COLORS["negative"] for v in values],
        font=dict(color="#ffffff", size=13),
        bordercolor="rgba(0,0,0,0)",
    )


def _hover_solid(color: str) -> dict:
    """単色hoverlabel設定（折れ線用）"""
    return dict(bgcolor=color, font=dict(color="#ffffff", size=13), bordercolor="rgba(0,0,0,0)")


def line_chart(df: pd.DataFrame, x: str, y: str, color_col: str, title: str) -> go.Figure:
    """投資家別折れ線グラフ"""
    fig = go.Figure()
    for inv_type, group in df.groupby(color_col):
        label = _label(inv_type)
        color = COLORS.get(label, "#aaaaaa")
        fig.add_trace(go.Scatter(
            x=group[x], y=group[y],
            mode="lines+markers",
            name=label,
            line=dict(color=color, width=2),
            marker=dict(size=5),
            hoverlabel=_hover_solid(color),
        ))
    fig.update_layout(
        title=title,
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="#ffffff"),
        legend=dict(bgcolor="#1a1a2e"),
        xaxis=dict(gridcolor="#333"),
        yaxis=dict(gridcolor="#333"),
    )
    return fig


def bar_chart(df: pd.DataFrame, x: str, y: str, title: str) -> go.Figure:
    """買い越し/売り越し棒グラフ（正=緑 / 負=赤）"""
    values = list(df[y])
    colors = [COLORS["positive"] if v >= 0 else COLORS["negative"] for v in values]
    fig = go.Figure(go.Bar(
        x=df[x], y=df[y],
        marker_color=colors,
        hoverlabel=_hover_pn(values),
    ))
    fig.update_layout(
        title=title,
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="#ffffff"),
        xaxis=dict(gridcolor="#333"),
        yaxis=dict(gridcolor="#333", zeroline=True, zerolinecolor="#555"),
    )
    return fig


def combined_bar_line(df: pd.DataFrame, x: str, bar_col: str, line_col: str, title: str) -> go.Figure:
    """棒グラフ＋折れ線の複合チャート"""
    values = list(df[bar_col])
    colors = [COLORS["positive"] if v >= 0 else COLORS["negative"] for v in values]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df[x], y=df[bar_col], name=bar_col,
        marker_color=colors, opacity=0.7,
        hoverlabel=_hover_pn(values),
    ))
    fig.add_trace(go.Scatter(
        x=df[x], y=df[line_col], name=line_col,
        line=dict(color="#00b4d8", width=2), yaxis="y2",
        hoverlabel=_hover_solid("#00b4d8"),
    ))
    fig.update_layout(
        title=title,
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="#ffffff"),
        yaxis=dict(gridcolor="#333"),
        yaxis2=dict(overlaying="y", side="right", gridcolor="#333"),
        legend=dict(bgcolor="#1a1a2e"),
    )
    return fig
