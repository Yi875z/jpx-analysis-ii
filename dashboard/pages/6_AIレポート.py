"""
AI需給分析レポート閲覧ページ
- Supabase reports テーブル + outputs/reports/ ファイルを統合
- 週次／月次の切り替え・過去レポート一覧から選択して閲覧
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from components.data_loader import get_report_list, get_report_content
from components.theme import render_theme_toggle

st.set_page_config(
    page_title="AIレポート｜JPX投資主体別売買動向ダッシュボード",
    page_icon="📋",
    layout="wide",
)

st.title("📋 AI需給分析レポート")
st.caption("Claude APIが生成した週次・月次の需給解釈レポート")

# ─── サイドバー ────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### レポート選択")
    report_type = st.radio(
        "種別",
        ["weekly", "monthly"],
        format_func=lambda x: "週次レポート" if x == "weekly" else "月次レポート",
    )
    st.divider()
    render_theme_toggle()
    st.divider()
    if st.button("キャッシュ更新"):
        st.cache_data.clear()
        st.rerun()

# ─── レポート一覧取得 ─────────────────────────────────────────
items = get_report_list(report_type=report_type)
if not items:
    st.info(
        "該当するレポートが見つかりません。\n\n"
        "週次レポートは `python main.py` 実行時に自動生成されます。\n"
        "月次レポートは `python main.py --monthly YYYY-MM` で生成可能です。"
    )
    st.stop()


def _label(item: dict) -> str:
    src_icon = "🗄️" if item["source"] == "db" else "📁"
    return f"{src_icon} {item['id']}"


col_sel, col_dl = st.columns([4, 1])
with col_sel:
    selected = st.selectbox(
        f"閲覧するレポート（全 {len(items)} 件）",
        items,
        format_func=_label,
        index=0,
    )

# ─── 本文取得 ─────────────────────────────────────────────────
content = get_report_content(selected["id"], report_type=report_type)

if not content:
    st.warning("レポート本文が取得できませんでした。")
    st.stop()

# ダウンロードボタン
with col_dl:
    fname = selected.get("file_name") or (
        f"jpx_investor_{selected['id'].replace('-', '')}.md"
        if report_type == "weekly"
        else f"jpx_monthly_{selected['id'].replace('-', '')}.md"
    )
    st.download_button(
        label="📥 ダウンロード",
        data=content.encode("utf-8"),
        file_name=fname,
        mime="text/markdown",
        use_container_width=True,
    )

src_desc = "Supabase DB" if selected["source"] == "db" else "outputs/reports/ ファイル"
st.caption(f"取得元: {src_desc} ／ ファイル名: `{fname}`")

st.divider()

# ─── レポート本文表示 ─────────────────────────────────────────
st.markdown(content)
