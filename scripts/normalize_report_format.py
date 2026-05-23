"""
scripts/normalize_report_format.py
==================================
過去レポートのファイル名・タイトル表記を統一フォーマットへ正規化する一回限りのスクリプト。

旧フォーマット:
  ファイル名: jpx_investor_YYYYMMDD.md     （週末日のみ）
  タイトル: # JPX投資家別売買動向 YYYY年MM月DD日週

新フォーマット:
  ファイル名: jpx_investor_YYYYMMDD_YYYYMMDD.md （週初_週末）
  タイトル: # JPX投資家別売買動向 YYYY年MM月DD日〜MM月DD日

処理対象:
  1. outputs/reports/ 配下のMarkdownファイル（リネーム + 内容書き換え）
  2. Supabase reports テーブルの file_name / content_md（content_md内のタイトル行のみ）

使い方:
  python scripts/normalize_report_format.py            # ドライラン（変更内容を表示するだけ）
  python scripts/normalize_report_format.py --apply    # 実行
"""

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

# Windows cp932 コンソールでも Unicode を出せるよう stdout を UTF-8 に
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.supabase_client import get_client

_REPORTS_DIR = Path(__file__).parent.parent / "outputs" / "reports"

_OLD_FNAME_RE = re.compile(r"^jpx_investor_(\d{8})\.md$")
_OLD_TITLE_RE = re.compile(r"^# JPX投資家別売買動向 (\d{4})年(\d{2})月(\d{2})日週\s*$", re.MULTILINE)


def _new_title(week_end: date) -> str:
    """週末日（金）から '# JPX投資家別売買動向 YYYY年MM月DD日〜MM月DD日' を生成"""
    week_start = week_end - timedelta(days=4)
    return (
        f"# JPX投資家別売買動向 "
        f"{week_start.strftime('%Y年%m月%d日')}〜{week_end.strftime('%m月%d日')}"
    )


def _new_filename(week_end: date) -> str:
    week_start = week_end - timedelta(days=4)
    return f"jpx_investor_{week_start.strftime('%Y%m%d')}_{week_end.strftime('%Y%m%d')}.md"


def _rewrite_content(content: str, week_end: date) -> str:
    """タイトル行を新フォーマットに置換する。
    追加で『> データソース: ...』直後に対象期間行を挿入（既にあれば触らない）。
    """
    new_title = _new_title(week_end)
    week_start = week_end - timedelta(days=4)
    period_line = f"> 対象期間: {week_start.strftime('%Y年%m月%d日')}〜{week_end.strftime('%m月%d日')}（月〜金）"

    # タイトル行を置換
    def _title_repl(_m: re.Match) -> str:
        return new_title
    content_new = _OLD_TITLE_RE.sub(_title_repl, content, count=1)

    # 対象期間行が未挿入なら、データソース行の直後に追加
    if "> 対象期間:" not in content_new:
        content_new = re.sub(
            r"^(> データソース:.*)$",
            lambda m: f"{m.group(1)}\n{period_line}",
            content_new,
            count=1,
            flags=re.MULTILINE,
        )
    return content_new


def normalize_files(apply: bool) -> list[dict]:
    """ファイルシステムを正規化。返り値: 変更ログ"""
    changes = []
    if not _REPORTS_DIR.exists():
        print(f"[skip] {_REPORTS_DIR} が存在しません")
        return changes

    for f in sorted(_REPORTS_DIR.glob("jpx_investor_*.md")):
        m = _OLD_FNAME_RE.match(f.name)
        if not m:
            continue  # 既に新フォーマット or 他形式
        date_str = m.group(1)
        try:
            week_end = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
        except ValueError:
            print(f"[skip] 日付パース不可: {f.name}")
            continue

        new_name = _new_filename(week_end)
        new_path = f.parent / new_name

        # 内容の書き換え
        old_content = f.read_text(encoding="utf-8")
        new_content = _rewrite_content(old_content, week_end)
        content_changed = old_content != new_content

        target_exists = new_path.exists()
        changes.append({
            "old_name": f.name,
            "new_name": new_name,
            "content_changed": content_changed,
            "target_exists": target_exists,
            "week_end": week_end,
        })

        if apply:
            if target_exists:
                # 既に新フォーマット版がある（再生成済み）→ 旧ファイルを削除
                f.unlink()
            else:
                if content_changed:
                    f.write_text(new_content, encoding="utf-8")
                f.rename(new_path)

    return changes


def normalize_db(apply: bool, file_changes: list[dict]) -> int:
    """Supabase reports テーブルを正規化"""
    sb = get_client()
    res = (sb.table("reports")
             .select("id,week_date,file_name,content_md,report_type,format")
             .eq("report_type", "weekly")
             .eq("format", "markdown")
             .execute())
    rows = res.data or []
    updated = 0

    for row in rows:
        old_fname = row.get("file_name") or ""
        m = _OLD_FNAME_RE.match(old_fname)
        if not m:
            continue  # 既に新フォーマット or 別の名前
        date_str = m.group(1)
        try:
            week_end = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
        except ValueError:
            continue

        new_fname = _new_filename(week_end)
        old_content = row.get("content_md") or ""
        new_content = _rewrite_content(old_content, week_end) if old_content else ""

        needs_update = (old_fname != new_fname) or (new_content and new_content != old_content)
        if not needs_update:
            continue

        print(f"  [DB] id={row['id']} {old_fname} → {new_fname} (content_changed={new_content != old_content})")
        if apply:
            payload = {"file_name": new_fname}
            if new_content and new_content != old_content:
                payload["content_md"] = new_content
            sb.table("reports").update(payload).eq("id", row["id"]).execute()
            updated += 1

    return updated


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="実際に変更を適用する")
    parser.add_argument("--skip-db", action="store_true", help="Supabase の更新をスキップ")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== レポート正規化 ({mode}) ===\n")

    print("[1/2] ファイルシステム正規化")
    changes = normalize_files(apply=args.apply)
    if not changes:
        print("  変更対象なし")
    else:
        for c in changes:
            flag = "✓" if c["content_changed"] else " "
            print(f"  {flag} {c['old_name']} → {c['new_name']}")
        print(f"  合計 {len(changes)} 件")

    print()
    print("[2/2] Supabase reports テーブル正規化")
    if args.skip_db:
        print("  --skip-db 指定によりスキップ")
    else:
        updated = normalize_db(apply=args.apply, file_changes=changes)
        if args.apply:
            print(f"  更新 {updated} 件")

    print()
    if not args.apply:
        print("※ ドライラン完了。実行するには --apply を付けてください")


if __name__ == "__main__":
    main()
