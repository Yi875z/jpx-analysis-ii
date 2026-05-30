"""
テーマ管理モジュール（ダーク / ライト切り替え）
config.toml は base="light" を前提とする。
- ライトモード: Streamlit ネイティブ light theme + 最小 CSS
- ダークモード: 包括的 CSS で完全ダーク化
  ※ [stMarkdownContainer] には * ワイルドカードを使わない
    → KPI カード等 inline-styled <div> が上書きされるのを防ぐ
"""
import streamlit as st

# ─── テーマ定義 ──────────────────────────────────────────────────
THEMES = {
    "dark": {
        "bg":        "#0e1117",
        "bg2":       "#1a1a2e",
        "text":      "#ffffff",
        "subtext":   "#aaaaaa",
        "border":    "#333333",
        "plot_bg":   "#0e1117",
        "paper_bg":  "#0e1117",
        "grid":      "#333333",
        "zero":      "#555555",
        "legend_bg": "#1a1a2e",
        "font_color":"#ffffff",
        "widget_bg": "#262640",
    },
    "light": {
        "bg":        "#f5f7fa",
        "bg2":       "#ffffff",
        "text":      "#1a1a2a",
        "subtext":   "#555555",
        "border":    "#cccccc",
        "plot_bg":   "#ffffff",
        "paper_bg":  "#f5f7fa",
        "grid":      "#dddddd",
        "zero":      "#999999",
        "legend_bg": "#f0f0f0",
        "font_color":"#1a1a2a",
        "widget_bg": "#ffffff",
    },
}


def get_theme() -> dict:
    """現在のテーマ設定を返す"""
    mode = st.session_state.get("theme_mode", "dark")
    return THEMES[mode]


def render_theme_toggle():
    """サイドバーにダーク/ライト切り替えボタンを表示し、CSSを注入する"""
    mode = st.session_state.get("theme_mode", "dark")
    label = "🌙 ダークモード" if mode == "light" else "☀️ ライトモード"
    if st.sidebar.button(label, use_container_width=True):
        st.session_state["theme_mode"] = "dark" if mode == "light" else "light"
        st.rerun()
    _inject_css(st.session_state.get("theme_mode", "dark"))


def _inject_css(mode: str):
    t = THEMES[mode]

    if mode == "light":
        st.markdown(f"""
        <style>
        /* ── Streamlit テーマ変数を上書き（ネイティブ部品をライトに揃える） ── */
        :root, .stApp, [data-testid="stApp"],
        [data-testid="stAppViewContainer"], [data-testid="stHeader"],
        [data-testid="stMain"], section[data-testid="stSidebar"] {{
            --background-color: {t['bg']} !important;
            --secondary-background-color: {t['bg2']} !important;
            --text-color: {t['text']} !important;
            --border-color: {t['border']} !important;
            --primary-color: #1f4e79 !important;
        }}
        /* ── メイン背景 ── */
        .stApp, [data-testid="stAppViewContainer"],
        [data-testid="stMain"], .block-container {{
            background-color: {t['bg']} !important;
            color: {t['text']} !important;
        }}

        /* ── サイドバー背景 ── */
        section[data-testid="stSidebar"],
        [data-testid="stSidebarContent"],
        [data-testid="stSidebarUserContent"],
        section[data-testid="stSidebar"] > div,
        section[data-testid="stSidebar"] > div:first-child {{
            background-color: {t['bg2']} !important;
        }}

        /* ── サイドバーテキスト全般 ── */
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] a,
        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3,
        section[data-testid="stSidebar"] li,
        section[data-testid="stSidebar"] div {{
            color: {t['text']} !important;
        }}

        /* ── マルチページナビゲーション（非アクティブ文字が薄グレーで同化する問題を修正） ── */
        /* 新しい Streamlit は stSidebarNavLink 内の span に分かれ、非アクティブ時に
           opacity が下がるため、color だけでなく opacity も明示的に戻す */
        [data-testid="stSidebarNav"] *,
        [data-testid="stSidebarNavItems"] *,
        [data-testid="stSidebarNavLink"] * {{
            color: {t['text']} !important;
            opacity: 1 !important;
        }}
        [data-testid="stSidebarNav"] a:hover,
        [data-testid="stSidebarNavLink"]:hover {{
            background-color: {t['bg']} !important;
        }}

        /* ── ボタン ── */
        section[data-testid="stSidebar"] button,
        section[data-testid="stSidebar"] [data-testid="baseButton-secondary"] {{
            background-color: {t['bg']} !important;
            color: {t['text']} !important;
            border-color: {t['border']} !important;
        }}

        /* ── ヘッダーバー（最上部の黒帯） ── */
        header[data-testid="stHeader"],
        [data-testid="stHeader"],
        [data-testid="stDecoration"],
        [data-testid="stToolbar"] {{
            background-color: {t['bg']} !important;
            color: {t['text']} !important;
        }}
        header[data-testid="stHeader"] button,
        header[data-testid="stHeader"] svg {{
            color: {t['text']} !important;
            fill: {t['text']} !important;
        }}

        /* ── マルチセレクト / ドロップダウン本体 ── */
        [data-baseweb="select"] > div,
        [data-baseweb="select"] > div:first-child,
        [data-baseweb="base-input"],
        [data-baseweb="input"] > div {{
            background-color: {t['widget_bg']} !important;
            border-color: {t['border']} !important;
            color: {t['text']} !important;
        }}

        /* ── 選択済みタグ（海外投資家 × 等） ── */
        [data-baseweb="tag"],
        [data-baseweb="tag"] span {{
            background-color: {t['border']} !important;
            color: {t['text']} !important;
        }}

        /* ── ドロップダウン内のテキスト ── */
        [data-baseweb="select"] span,
        [data-baseweb="select"] div {{
            color: {t['text']} !important;
            background-color: transparent;
        }}

        /* ── ポップオーバー / 検索結果リスト（body直下portal含む） ── */
        [data-baseweb="popover"],
        [data-baseweb="popover"] > div,
        body [data-baseweb="popover"],
        body [data-baseweb="popover"] > div {{
            background-color: {t['bg2']} !important;
        }}
        [data-baseweb="menu"],
        [data-baseweb="menu"] > ul,
        [data-baseweb="menu"] li,
        [data-baseweb="menu"] li > div,
        body [data-baseweb="menu"],
        body [data-baseweb="menu"] li,
        body [data-baseweb="menu"] li > div {{
            background-color: {t['bg2']} !important;
            color: {t['text']} !important;
        }}
        ul[role="listbox"],
        ul[role="listbox"] li,
        li[role="option"],
        li[role="option"] > div {{
            background-color: {t['bg2']} !important;
            color: {t['text']} !important;
        }}
        li[role="option"]:hover,
        li[role="option"][aria-selected="true"] {{
            background-color: {t['bg']} !important;
        }}

        /* ── 「検索結果なし」テキスト ── */
        [data-baseweb="menu"] p,
        [data-baseweb="menu"] span,
        body [data-baseweb="menu"] p,
        body [data-baseweb="menu"] span {{
            background-color: {t['bg2']} !important;
            color: {t['subtext']} !important;
        }}

        /* ── expander ヘッダー（ライトモードで暗背景・暗文字に同化する問題を修正） ── */
        [data-testid="stExpander"] {{
            border-color: {t['border']} !important;
        }}
        [data-testid="stExpander"] details,
        [data-testid="stExpander"] summary {{
            background-color: {t['bg2']} !important;
            color: {t['text']} !important;
        }}
        [data-testid="stExpander"] summary p,
        [data-testid="stExpander"] summary span,
        [data-testid="stExpander"] summary svg {{
            color: {t['text']} !important;
            fill: {t['text']} !important;
        }}

        /* ── テーブル（HTMLテーブル: st.markdown(df.to_html)） ── */
        .dataframe, table {{
            background-color: {t['bg2']} !important;
            color: {t['text']} !important;
            border-collapse: collapse;
        }}
        .dataframe td, .dataframe th, table td, table th {{
            border: 1px solid {t['border']} !important;
            color: {t['text']} !important;
            padding: 4px 10px;
        }}
        thead tr th {{
            background-color: {t['bg']} !important;
            color: {t['text']} !important;
        }}

        /* ── divider ── */
        hr {{ border-color: {t['border']} !important; }}
        </style>
        """, unsafe_allow_html=True)
        return

    # ─── ダークモード: Streamlit の light base を完全上書き ───────
    # 重要: [stMarkdownContainer] には * ワイルドカードを使わない
    # → KPI カード等 inline-styled <div> が !important で上書きされるのを防ぐ
    st.markdown(f"""
    <style>
    /* ── Streamlit テーマ変数を上書き（ボタン/ヘッダー/expander 等のネイティブ部品は
          内部CSSが var(--*) を参照しているため、変数自体を書き換えるのが最も確実） ── */
    :root, .stApp, [data-testid="stApp"],
    [data-testid="stAppViewContainer"], [data-testid="stHeader"],
    [data-testid="stMain"], section[data-testid="stSidebar"] {{
        --background-color: {t['bg']} !important;
        --secondary-background-color: {t['bg2']} !important;
        --text-color: {t['text']} !important;
        --border-color: {t['border']} !important;
        --primary-color: #29b6f6 !important;
    }}
    /* ── 背景 ── */
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    .block-container {{
        background-color: {t['bg']} !important;
    }}
    section[data-testid="stSidebar"],
    [data-testid="stSidebarContent"] {{
        background-color: {t['bg2']} !important;
    }}

    /* ── .stApp テキスト（子要素は継承するがinline styleで上書き可） ── */
    .stApp {{
        color: {t['text']} !important;
    }}

    /* ── Markdown / Caption テキスト（p, li 等のみ。div は除外） ── */
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stMarkdownContainer"] h1,
    [data-testid="stMarkdownContainer"] h2,
    [data-testid="stMarkdownContainer"] h3,
    [data-testid="stMarkdownContainer"] h4,
    [data-testid="stMarkdownContainer"] span:not([style]),
    [data-testid="stCaptionContainer"] p,
    [data-testid="stCaptionContainer"] span {{
        color: {t['text']} !important;
    }}

    /* ── サイドバーテキスト ── */
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] div {{
        color: {t['text']} !important;
    }}

    /* ── ウィジェット背景 ── */
    [data-baseweb="input"] > div,
    [data-baseweb="base-input"],
    [data-baseweb="select"] > div:first-child {{
        background-color: {t['widget_bg']} !important;
        border-color: {t['border']} !important;
        color: {t['text']} !important;
    }}
    [data-baseweb="popover"],
    [data-baseweb="popover"] li {{
        background-color: {t['bg2']} !important;
        color: {t['text']} !important;
    }}
    [data-baseweb="tag"] {{
        background-color: {t['border']} !important;
        color: {t['text']} !important;
    }}

    /* ── ラジオ・チェックボックス ── */
    [role="radiogroup"] label,
    [data-baseweb="radio"] label,
    [data-baseweb="checkbox"] label {{
        color: {t['text']} !important;
    }}

    /* ── タブ ── */
    [data-baseweb="tab-list"] {{
        background-color: {t['bg']} !important;
    }}
    [data-baseweb="tab"],
    [data-baseweb="tab-panel"] {{
        background-color: {t['bg']} !important;
        color: {t['text']} !important;
    }}

    /* ── ボタン（新旧testid・サイドバー・ダウンロード含む） ── */
    [data-testid="baseButton-secondary"],
    [data-testid="baseButton-primary"],
    [data-testid="stBaseButton-secondary"],
    [data-testid="stBaseButton-primary"],
    .stButton button,
    .stDownloadButton button,
    [data-testid="stDownloadButton"] button,
    section[data-testid="stSidebar"] button {{
        background-color: {t['bg2']} !important;
        color: {t['text']} !important;
        border-color: {t['border']} !important;
    }}
    .stButton button p,
    .stDownloadButton button p,
    section[data-testid="stSidebar"] button p,
    .stButton button span,
    .stDownloadButton button span {{
        color: {t['text']} !important;
    }}

    /* ── アラート ── */
    [data-testid="stNotification"],
    div[class*="stAlert"] {{
        background-color: {t['bg2']} !important;
        color: {t['text']} !important;
    }}

    /* ── テーブル（HTMLテーブル: st.markdown(df.to_html)） ── */
    .dataframe, table {{
        background-color: {t['bg2']} !important;
        color: {t['text']} !important;
        border-color: {t['border']} !important;
    }}
    .dataframe td, .dataframe th, table td, table th {{
        border-color: {t['border']} !important;
        color: {t['text']} !important;
    }}
    thead tr th {{
        background-color: {t['bg']} !important;
        color: {t['subtext']} !important;
    }}

    /* ── ヘッダーバー・ツールバー（config がライトのため明示的に暗くする） ── */
    header[data-testid="stHeader"],
    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"] {{
        background-color: {t['bg']} !important;
        color: {t['text']} !important;
    }}
    header[data-testid="stHeader"] *,
    [data-testid="stToolbar"] * {{
        color: {t['text']} !important;
        fill: {t['text']} !important;
    }}

    /* ── expander ヘッダー ── */
    [data-testid="stExpander"] {{
        border-color: {t['border']} !important;
    }}
    [data-testid="stExpander"] details,
    [data-testid="stExpander"] summary {{
        background-color: {t['bg2']} !important;
        color: {t['text']} !important;
    }}
    [data-testid="stExpander"] summary p,
    [data-testid="stExpander"] summary span,
    [data-testid="stExpander"] summary svg {{
        color: {t['text']} !important;
        fill: {t['text']} !important;
    }}

    /* ── マルチページナビ（非アクティブの薄さを解消） ── */
    [data-testid="stSidebarNav"] *,
    [data-testid="stSidebarNavItems"] *,
    [data-testid="stSidebarNavLink"] * {{
        color: {t['text']} !important;
        opacity: 1 !important;
    }}

    /* ── divider ── */
    hr {{ border-color: {t['border']} !important; }}
    </style>
    """, unsafe_allow_html=True)


def plot_layout(**kwargs) -> dict:
    """Plotlyグラフのlayout共通設定をテーマに合わせて返す（ネストdict深合成）"""
    t = get_theme()
    base = dict(
        template      = {},           # Plotlyデフォルトテンプレートの干渉を排除
        plot_bgcolor  = t["plot_bg"],
        paper_bgcolor = t["paper_bg"],
        font          = dict(color=t["font_color"], family="sans-serif"),
        legend        = dict(
                             bgcolor=t["legend_bg"],
                             bordercolor=t["border"],
                             borderwidth=1,
                             font=dict(color=t["font_color"], size=12),
                         ),
        xaxis         = dict(gridcolor=t["grid"],
                             tickfont=dict(color=t["font_color"]),
                             title_font=dict(color=t["font_color"])),
        yaxis         = dict(gridcolor=t["grid"],
                             zeroline=True, zerolinecolor=t["zero"],
                             tickfont=dict(color=t["font_color"]),
                             title_font=dict(color=t["font_color"])),
    )
    for key, val in kwargs.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            base[key] = {**base[key], **val}
        else:
            base[key] = val
    return base
