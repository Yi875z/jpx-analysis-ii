"""
実行ログ閲覧ページ
- fetch_logs テーブル（GitHub Actions 週次自動実行の記録）を表示
- 直近の成功/失敗・処理件数・所要時間をアプリ内で確認できる
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from components.data_loader import ensure_fresh, get_fetch_logs
from components.theme import render_theme_toggle

st.set_page_config(
    page_title="実行ログ｜JPX投資主体別売買動向ダッシュボード",
    page_icon="🗂",
    layout="wide",
)

ensure_fresh()
st.title("🗂 実行ログ")
st.caption("週次自動実行（GitHub Actions 木曜18:17 JST）のデータ取得・レポート生成履歴")

# ─── サイドバー ────────────────────────────────────────────────
with st.sidebar:
    render_theme_toggle()
    st.divider()
    if st.button("キャッシュ更新"):
        st.cache_data.clear()
        st.rerun()

# ─── ログ取得 ─────────────────────────────────────────────────
df = get_fetch_logs(100)
if df.empty:
    st.info("実行ログがまだありません。木曜の自動実行後に記録されます。")
    st.stop()

# UTC → JST 表示
df["run_at"] = (
    pd.to_datetime(df["run_at"], utc=True, format="ISO8601")
    .dt.tz_convert("Asia/Tokyo")
    .dt.strftime("%Y-%m-%d %H:%M")
)

# ─── サマリーメトリクス ────────────────────────────────────────
latest = df.iloc[0]
recent10 = df.head(10)
ok10 = int((recent10["status"] == "success").sum())

c1, c2, c3 = st.columns(3)
c1.metric("最終実行 (JST)", latest["run_at"])
c2.metric(
    "最終ステータス",
    "✅ success" if latest["status"] == "success" else f"❌ {latest['status']}",
)
c3.metric("直近10回成功率", f"{ok10 * 100 // len(recent10)}%")

st.divider()

# ─── 履歴テーブル ─────────────────────────────────────────────
show = df.copy()
show["status"] = show["status"].map(
    lambda s: "✅ success" if s == "success" else f"❌ {s}"
)
show = show.rename(columns={
    "run_at":        "実行日時(JST)",
    "week_date":     "対象週",
    "status":        "結果",
    "spot_rows":     "現物行数",
    "futures_rows":  "先物行数",
    "duration_sec":  "所要秒",
    "error_message": "エラー内容",
})
cols = [c for c in ["実行日時(JST)", "対象週", "結果", "現物行数",
                    "先物行数", "所要秒", "エラー内容"] if c in show.columns]
st.dataframe(show[cols], use_container_width=True, hide_index=True)

# ─── 失敗詳細 ─────────────────────────────────────────────────
err_df = df[df["status"] != "success"]
if not err_df.empty:
    with st.expander(f"❌ 失敗ログ詳細（{len(err_df)}件）", expanded=False):
        for _, r in err_df.iterrows():
            st.markdown(
                f"**{r['run_at']}**（対象週 {r.get('week_date') or '-'}）: "
                f"{r.get('error_message') or '(詳細なし)'}"
            )
