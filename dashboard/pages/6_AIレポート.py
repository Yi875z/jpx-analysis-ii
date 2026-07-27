"""
AI需給分析レポート閲覧ページ
- Supabase reports テーブル + outputs/reports/ ファイルを統合
- 週次／月次の切り替え・過去レポート一覧から選択して閲覧
"""
import sys
from datetime import date
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from components.data_loader import (
    ensure_fresh,
    get_report_list,
    get_report_content,
    is_report_complete,
    build_excel_export,
)
from components.theme import render_theme_toggle

st.set_page_config(
    page_title="AIレポート｜JPX投資主体別売買動向ダッシュボード",
    page_icon="📋",
    layout="wide",
)

ensure_fresh()
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


id_to_item = {it["id"]: it for it in items}
ids = [it["id"] for it in items]  # 新しい順
sel_key = f"report_sel_{report_type}"

# 種別切替やキャッシュ更新で選択中IDが消えた場合は最新に戻す
if st.session_state.get(sel_key) not in ids:
    st.session_state[sel_key] = ids[0]
cur_idx = ids.index(st.session_state[sel_key])


def _label(rid: str) -> str:
    src_icon = "🗄️" if id_to_item[rid]["source"] == "db" else "📁"
    return f"{src_icon} {rid}"


def _move(delta: int):
    i = ids.index(st.session_state[sel_key]) if st.session_state[sel_key] in ids else 0
    st.session_state[sel_key] = ids[min(max(i + delta, 0), len(ids) - 1)]


col_prev, col_sel, col_next, col_dl = st.columns([1, 3, 1, 1.2])
with col_prev:
    st.write("")  # selectboxのラベル分の高さ合わせ
    st.button(
        "◀ 前へ", use_container_width=True,
        disabled=(cur_idx >= len(ids) - 1),
        on_click=_move, args=(1,),
        help="1つ古いレポートへ",
    )
with col_next:
    st.write("")
    st.button(
        "次へ ▶", use_container_width=True,
        disabled=(cur_idx <= 0),
        on_click=_move, args=(-1,),
        help="1つ新しいレポートへ",
    )
with col_sel:
    selected_id = st.selectbox(
        f"閲覧するレポート（全 {len(items)} 件）",
        ids,
        format_func=_label,
        key=sel_key,
    )
selected = id_to_item[selected_id]

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

if not is_report_complete(content):
    st.warning(
        "⚠️ このレポートは末尾が途中で切れている可能性があります"
        "（生成時のトークン上限による切断の疑い）。"
        "`python main.py --report-only --date YYYY-MM-DD` で再生成できます。"
    )

st.divider()

# ─── レポート本文表示 ─────────────────────────────────────────
st.markdown(content)

st.divider()

# ─── ChatGPT査読用プロンプト ──────────────────────────────────
_REVIEW_TPL = Path(__file__).parent.parent.parent / "docs" / "chatgpt_review_prompt.md"
with st.expander("🔎 外部AI査読用プロンプト（ChatGPT等でセカンドオピニオン）"):
    if _REVIEW_TPL.exists():
        st.caption(
            "下のブロック右上のコピーアイコンで全文コピーし、ChatGPT等に貼り付けてください。"
            "符号規約・GEX定義・査読タスクと、このレポート全文が一体になっています。"
        )
        st.code(
            _REVIEW_TPL.read_text(encoding="utf-8") + "\n" + content,
            language=None,
        )
    else:
        st.info("docs/chatgpt_review_prompt.md が見つかりません。")

# ─── Excelデータエクスポート ──────────────────────────────────
with st.expander("📊 Excelデータエクスポート"):
    st.caption(
        "Supabase蓄積データ（現物・先物・合算・Zスコア・月次）を"
        "1つのExcelブックにまとめてダウンロードします。"
    )
    if st.button("Excelを生成する"):
        st.session_state["excel_export_bytes"] = build_excel_export()
    if st.session_state.get("excel_export_bytes"):
        st.download_button(
            "📥 Excelをダウンロード",
            data=st.session_state["excel_export_bytes"],
            file_name=f"jpx_data_export_{date.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
