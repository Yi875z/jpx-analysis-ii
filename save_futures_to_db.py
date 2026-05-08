"""
save_futures_to_db.py
=====================
JPX先物CSVをパースしてSupabaseのweekly_futuresテーブルに保存する。

使い方:
  python save_futures_to_db.py Tousi_DV_W_202603_4_0323_0327.csv 2026-03-27

  引数を省略した場合はデフォルト値を使用。

事前準備:
  config/.env に以下を設定済みであること
    SUPABASE_URL=https://syyojlcrnachuvrbvttw.supabase.co
    SUPABASE_KEY=eyJ...（サービスロールキー or アノンキー）
"""

import sys
import os
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

# ── 同フォルダの修正済みパーサーをインポート ──────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))
from parse_futures_csv import parse_futures_csv

# ── 環境変数ロード ────────────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(__file__), "config", ".env"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ SUPABASE_URL / SUPABASE_KEY が .env に設定されていません")
    sys.exit(1)


def save_futures(filepath: str, week_date: str) -> None:
    """先物データをパースしてSupabaseに保存する。"""

    # ── 1. パース ──────────────────────────────────────────────────────
    print(f"\n[1/3] CSVパース中: {filepath}")
    records = parse_futures_csv(filepath, week_date)
    print(f"      → {len(records)} レコード取得")

    if not records:
        print("⚠️  レコードが0件でした。CSVパスと週日を確認してください。")
        return

    # ── 2. Supabase接続 ────────────────────────────────────────────────
    print("\n[2/3] Supabase接続中...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("      → 接続OK")

    # ── 3. upsert（重複週は上書き） ──────────────────────────────────
    print(f"\n[3/3] weekly_futures テーブルへ保存中 ({week_date})...")

    # 既存データの削除（同週の再実行対応）
    supabase.table("weekly_futures") \
        .delete() \
        .eq("week_date", week_date) \
        .execute()

    # 挿入
    res = supabase.table("weekly_futures").insert(records).execute()

    inserted = len(res.data) if res.data else 0
    print(f"      → {inserted} 件 INSERT 完了")

    # ── 4. ログ記録 ────────────────────────────────────────────────────
    log = {
        "run_at":       datetime.now().isoformat(),
        "week_date":    week_date,
        "status":       "success",
        "futures_rows": inserted,
    }
    supabase.table("fetch_logs").insert(log).execute()

    print(f"\n✅ 完了: {week_date} の先物データ {inserted} 件を保存しました")
    print("   次のステップ: python agents/report_agent.py")


if __name__ == "__main__":
    filepath  = sys.argv[1] if len(sys.argv) > 1 else \
                "Tousi_DV_W_202603_4_0323_0327.csv"
    week_date = sys.argv[2] if len(sys.argv) > 2 else "2026-03-27"

    save_futures(filepath, week_date)
