"""
scripts/fix_mislabeled_reports.py
=================================
audit_week_dates.py で誤ラベル修正したweek_dateに合わせて、
ローカルファイル名・タイトル行・対象期間行・Supabase reports.content_md / file_name
を一括で正しい週末日に揃える。

修正対象（旧 → 新 週末日）:
  2026-05-22 → 2026-05-15
  2026-05-01 → 2026-04-24

使い方:
  python scripts/fix_mislabeled_reports.py            # ドライラン
  python scripts/fix_mislabeled_reports.py --apply    # 適用
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.supabase_client import get_client

_REPORTS_DIR = Path(__file__).parent.parent / "outputs" / "reports"

# 誤ラベル → 正しい週末日
FIXES = {
    date(2026, 5, 22): date(2026, 5, 15),
    date(2026, 5,  1): date(2026, 4, 24),
}


def _fname(week_end: date) -> str:
    ws = week_end - timedelta(days=4)
    return f"jpx_investor_{ws.strftime('%Y%m%d')}_{week_end.strftime('%Y%m%d')}.md"


def _label_full(week_end: date) -> str:
    """ '2026年05月18日〜05月22日' """
    ws = week_end - timedelta(days=4)
    return f"{ws.strftime('%Y年%m月%d日')}〜{week_end.strftime('%m月%d日')}"


def _rewrite(content: str, old_end: date, new_end: date) -> str:
    old_label = _label_full(old_end)
    new_label = _label_full(new_end)
    # タイトル行と対象期間行は同じ表記を使うので一括置換でOK
    return content.replace(old_label, new_label)


def fix_files(apply: bool) -> None:
    for old_end, new_end in FIXES.items():
        old_path = _REPORTS_DIR / _fname(old_end)
        new_path = _REPORTS_DIR / _fname(new_end)
        if not old_path.exists():
            print(f"  [skip] {old_path.name} 不在")
            continue
        if new_path.exists() and new_path != old_path:
            print(f"  [skip] 衝突: {new_path.name} 既存")
            continue

        old_content = old_path.read_text(encoding="utf-8")
        new_content = _rewrite(old_content, old_end, new_end)
        print(f"  {old_path.name} -> {new_path.name}  (content_changed={old_content != new_content})")
        if apply:
            if old_content != new_content:
                old_path.write_text(new_content, encoding="utf-8")
            if old_path != new_path:
                old_path.rename(new_path)


def fix_reports_db(apply: bool) -> None:
    sb = get_client()
    for old_end, new_end in FIXES.items():
        # この時点で audit_week_dates が week_date を既に更新しているため
        # reports.week_date は new_end になっているはず。
        # content_md と file_name は古い表記のままなので書き換える。
        res = (sb.table("reports")
                 .select("id,week_date,file_name,content_md")
                 .eq("week_date", new_end.isoformat())
                 .eq("format", "markdown")
                 .execute())
        for row in res.data or []:
            old_fname = row.get("file_name") or ""
            old_content = row.get("content_md") or ""
            new_fname = _fname(new_end)
            new_content = _rewrite(old_content, old_end, new_end) if old_content else ""

            need = (old_fname != new_fname) or (new_content and new_content != old_content)
            if not need:
                continue

            print(f"  [DB id={row['id']}] {old_fname or '(none)'} -> {new_fname}  "
                  f"(content_changed={bool(new_content) and new_content != old_content})")
            if apply:
                payload = {"file_name": new_fname}
                if new_content and new_content != old_content:
                    payload["content_md"] = new_content
                sb.table("reports").update(payload).eq("id", row["id"]).execute()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== 誤ラベル付き レポート ファイル/DB修正 ({mode}) ===\n")
    print("[1/2] ローカルファイル")
    fix_files(apply=args.apply)
    print()
    print("[2/2] Supabase reports テーブル")
    fix_reports_db(apply=args.apply)


if __name__ == "__main__":
    main()
