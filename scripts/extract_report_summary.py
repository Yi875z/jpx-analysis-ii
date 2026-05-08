"""
scripts/extract_report_summary.py
n8nワークフローから呼び出して最新レポートのエグゼクティブサマリーを
stdout に出力するヘルパースクリプト。

使い方:
  python scripts/extract_report_summary.py
"""

import glob
import io
import os
import sys

# Windows CP932環境でもUTF-8出力できるようにする
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs", "reports")

def main():
    files = sorted(
        glob.glob(os.path.join(REPORT_DIR, "*.md")),
        key=os.path.getmtime,
        reverse=True,
    )
    if not files:
        print("[エラー] レポートファイルが見つかりません", file=sys.stderr)
        sys.exit(1)

    latest = files[0]
    text = open(latest, encoding="utf-8").read()

    # エグゼクティブサマリー部分を抽出
    summary_start = text.find("## 📋 エグゼクティブサマリー")
    next_section  = text.find("\n## ", summary_start + 1) if summary_start != -1 else -1

    if summary_start != -1 and next_section != -1:
        summary = text[summary_start:next_section].strip()
    else:
        # 見つからなければ先頭3000文字
        summary = text[:3000]

    print(f"=== {os.path.basename(latest)} ===\n")
    print(summary)

if __name__ == "__main__":
    main()
