"""
scripts/audit_week_dates.py
===========================
DB の weekly_spot / weekly_futures / weekly_combined / weekly_stats / reports の
week_date と、source_url から取得できるファイル名 → JPX対応期間を照合する。

JPX インデックスページ上のマッピングは最新数週分しか取得できないため、
照合できない過去レコードは「unknown」扱いで一覧表示する（誤判定を防ぐ）。

使い方:
  python scripts/audit_week_dates.py                  # 全照合（読み取りのみ）
  python scripts/audit_week_dates.py --fix            # ズレているレコードを修正
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.supabase_client import get_client
from scripts.jpx_week_resolver import (
    extract_filename_stem,
    resolve_from_jpx,
)


SPOT_TABLES = ["weekly_spot"]  # source_url を持つテーブル
ALL_RELATED_TABLES = [
    "weekly_spot",      # source_url あり
    "weekly_futures",   # source_url あり
    "weekly_combined",  # week_date のみ（追従更新）
    "weekly_stats",     # week_date のみ
    "reports",          # week_date + file_name + content_md
]


def fetch_source_urls(sb) -> dict[str, set[str]]:
    """{week_date: set(source_url)} を weekly_spot から取得"""
    out: dict[str, set[str]] = defaultdict(set)
    offset = 0
    page = 1000
    while True:
        res = (sb.table("weekly_spot")
                .select("week_date,source_url")
                .order("week_date", desc=True)
                .range(offset, offset + page - 1)
                .execute())
        rows = res.data or []
        for r in rows:
            wd = r.get("week_date")
            src = r.get("source_url") or ""
            if wd:
                out[wd].add(src)
        if len(rows) < page:
            break
        offset += page
    return out


def audit(apply_fix: bool) -> None:
    sb = get_client()

    print("[1/3] JPX 公開中のマッピングを取得")
    jpx_map = resolve_from_jpx()
    print(f"  取得 {len(jpx_map)} 件")
    for stem, wi in sorted(jpx_map.items(), key=lambda x: x[1].week_end, reverse=True):
        print(f"    {stem}: {wi.week_start} 〜 {wi.week_end}")

    print()
    print("[2/3] DB の weekly_spot を走査して照合")
    db_map = fetch_source_urls(sb)
    print(f"  対象 week_date: {len(db_map)} 件")

    discrepancies: list[dict] = []  # {old_week_date, new_week_date, stem}

    for wd, urls in sorted(db_map.items(), reverse=True):
        for url in urls:
            stem = extract_filename_stem(url)
            if not stem:
                continue
            wi = jpx_map.get(stem)
            if wi is None:
                continue  # 過去アーカイブ範囲外
            expected = wi.week_end.isoformat()
            if expected == wd:
                print(f"  OK  {wd}  ({stem})")
            else:
                print(f"  >>> ZRE  DB:{wd} != 実態:{expected}  (file={stem})")
                discrepancies.append({
                    "old": wd, "new": expected, "stem": stem,
                })

    print()
    if not discrepancies:
        print("[3/3] 修正対象なし。終了。")
        return

    print(f"[3/3] {'修正実行' if apply_fix else 'ドライラン'} - 対象 {len(discrepancies)} 件")
    for d in discrepancies:
        print(f"  {d['old']} -> {d['new']}  ({d['stem']})")
        if not apply_fix:
            continue

        old, new = d["old"], d["new"]
        # 既に new_date のレコードがあれば skip（重複防止）
        for tbl in ALL_RELATED_TABLES:
            try:
                # 上書きするとunique制約で衝突する可能性 → 先に new側を確認
                conflict = (sb.table(tbl).select("week_date")
                             .eq("week_date", new).limit(1).execute())
                if conflict.data:
                    print(f"    [skip] {tbl}: 既に {new} のレコードが存在")
                    continue
                # week_date を更新
                upd = sb.table(tbl).update({"week_date": new}).eq("week_date", old).execute()
                n = len(upd.data) if upd.data else 0
                print(f"    [{tbl}] {n} 行更新")
            except Exception as e:
                print(f"    [error] {tbl}: {e}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fix", action="store_true", help="実際にDBを修正する")
    args = p.parse_args()

    mode = "APPLY" if args.fix else "DRY-RUN"
    print(f"=== week_date 監査 ({mode}) ===")
    print()
    audit(apply_fix=args.fix)


if __name__ == "__main__":
    main()
