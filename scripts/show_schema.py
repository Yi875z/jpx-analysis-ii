"""
Supabase スキーマ確認スクリプト
information_schema からテーブル名・カラム名・型を一覧表示する
"""
import os
import sys
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / "config" / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")

if not SUPABASE_KEY:
    sys.exit("ERROR: SUPABASE_SERVICE_KEY が .env に設定されていません")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# information_schema.columns から public スキーマのカラム情報を取得
query = """
SELECT
    table_name,
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position
"""

resp = requests.post(
    f"{SUPABASE_URL}/rest/v1/rpc/query",
    headers=HEADERS,
    json={"query": query},
)

# /rpc/query が使えない場合は PostgREST の直接SQL実行エンドポイントを使う
if resp.status_code != 200:
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/exec_sql",
        headers=HEADERS,
        json={"sql": query},
    )

# どちらも失敗した場合は Management API (postgres) 経由で試みる
if resp.status_code != 200:
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/",
        headers={**HEADERS, "Accept": "application/json"},
    )
    # フォールバック: PostgREST の OpenAPI から取得
    print("[INFO] SQL実行RPCが利用不可のため、PostgREST OpenAPIからスキーマを取得します\n")
    data = resp.json()
    definitions = data.get("definitions", {})
    if not definitions:
        sys.exit("スキーマ情報を取得できませんでした。Supabaseのサービスロールキーを確認してください。")

    current_table = None
    for table_name, table_def in sorted(definitions.items()):
        print(f"■ {table_name}")
        for col_name, col_def in table_def.get("properties", {}).items():
            col_type = col_def.get("format") or col_def.get("type", "unknown")
            desc = col_def.get("description", "")
            print(f"    {col_name:<30} {col_type:<20} {desc}")
        print()
    sys.exit(0)

rows = resp.json()
if isinstance(rows, dict) and "message" in rows:
    sys.exit(f"ERROR: {rows['message']}")

# 結果を整形して表示
current_table = None
for row in rows:
    tbl = row["table_name"]
    if tbl != current_table:
        if current_table is not None:
            print()
        print(f"■ {tbl}")
        current_table = tbl
    nullable = "" if row["is_nullable"] == "YES" else " NOT NULL"
    default  = f" DEFAULT {row['column_default']}" if row["column_default"] else ""
    print(f"    {row['column_name']:<30} {row['data_type']:<20}{nullable}{default}")

print(f"\n合計 {len(set(r['table_name'] for r in rows))} テーブル / {len(rows)} カラム")
