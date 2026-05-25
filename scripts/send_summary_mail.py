"""
scripts/send_summary_mail.py
============================
Supabase reports テーブルから最新週のAIレポートを取得し、
エグゼクティブサマリーを抽出してGmailで送信する。

GitHub Actions の毎週木曜実行の最後に呼び出される想定。
SMTP_USER / SMTP_APP_PASSWORD が未設定なら静かにスキップ。

環境変数（.env または GitHub Secrets）:
  SMTP_HOST          = smtp.gmail.com (デフォルト)
  SMTP_PORT          = 587 (デフォルト)
  SMTP_USER          = 送信元 Gmail アドレス
  SMTP_APP_PASSWORD  = Gmail アプリパスワード（16文字）
  NOTIFY_EMAIL       = 送信先（未設定なら SMTP_USER と同じ）
"""

from __future__ import annotations

import argparse
import logging
import os
import smtplib
import sys
from datetime import date, timedelta
from email.mime.text import MIMEText
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "config" / ".env")

from db import supabase_client as db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DASHBOARD_URL = "https://jpx-investor-flow.streamlit.app"


def _extract_section(md: str, keyword: str) -> str:
    """## レベル見出しに keyword を含むセクションを抽出"""
    if not md:
        return ""
    out: list[str] = []
    in_section = False
    for line in md.split("\n"):
        if line.startswith("##") and not line.startswith("###"):
            if keyword in line:
                in_section = True
                continue
            elif in_section:
                break
        if in_section:
            out.append(line)
    text = "\n".join(out).strip()
    while text.endswith("---"):
        text = text[:-3].rstrip()
    return text


def fetch_latest_weekly_report() -> dict | None:
    """Supabase reports から最新の週次レポートを取得"""
    sb = db.get_client()
    res = (sb.table("reports")
             .select("week_date,content_md,file_name")
             .eq("report_type", "weekly")
             .eq("format", "markdown")
             .order("week_date", desc=True)
             .limit(1)
             .execute())
    if not res.data:
        return None
    return res.data[0]


def fetch_latest_alerts() -> list[dict]:
    """outputs/alerts/latest.json があれば読み込む"""
    alert_path = Path(__file__).parent.parent / "outputs" / "alerts" / "latest.json"
    if not alert_path.exists():
        return []
    try:
        import json
        data = json.loads(alert_path.read_text(encoding="utf-8"))
        return data.get("alerts", [])
    except Exception:
        return []


def build_mail_body(report: dict, alerts: list[dict]) -> tuple[str, str]:
    """件名と本文を構築"""
    wd = report["week_date"]
    content = report.get("content_md") or ""

    # 期間表記（YYYY-MM-DD から YYYY年MM月DD日〜MM月DD日 を計算）
    try:
        we = date.fromisoformat(wd)
        ws = we - timedelta(days=4)
        period_label = f"{ws.strftime('%Y年%m月%d日')}〜{we.strftime('%m月%d日')}"
    except Exception:
        period_label = wd

    summary = _extract_section(content, "エグゼクティブサマリー")
    if not summary:
        summary = "(エグゼクティブサマリーが抽出できませんでした)"

    # アラート部分
    alert_block = ""
    if alerts:
        alert_lines = [f"⚠️ 検出アラート ({len(alerts)} 件):", ""]
        for a in alerts:
            level = a.get("level", "info").upper()
            title = a.get("title", "")
            alert_lines.append(f"  [{level}] {title}")
        alert_block = "\n".join(alert_lines) + "\n\n"

    body = f"""JPX 投資主体別売買動向 — 週次レポート

【対象期間】 {period_label}

{alert_block}【エグゼクティブサマリー】

{summary}

────────────────────────────────────────
📊 ダッシュボード（全文閲覧・グラフ・オプション分析）:
{DASHBOARD_URL}

⚙ 取得処理: GitHub Actions による自動実行
🤖 AIレポート生成: Claude Sonnet 4.6
"""
    subject = f"[JPX需給] {period_label} レポート完成 ({len(alerts)} アラート)" if alerts \
              else f"[JPX需給] {period_label} レポート完成"
    return subject, body


def send_mail(subject: str, body: str) -> bool:
    user = os.environ.get("SMTP_USER")
    pw   = os.environ.get("SMTP_APP_PASSWORD") or os.environ.get("SMTP_PASSWORD")
    to   = os.environ.get("NOTIFY_EMAIL") or user

    if not (user and pw and to):
        logger.info("[skip] SMTP 未設定のため送信スキップ "
                    "(.env / GitHub Secrets に SMTP_USER / SMTP_APP_PASSWORD を設定すると送信)")
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to

    try:
        host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        port = int(os.environ.get("SMTP_PORT", 587))
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
        logger.info(f"[OK] サマリーメール送信成功: {to}")
        return True
    except Exception as e:
        logger.error(f"[NG] メール送信失敗: {e}")
        return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="送信せずにメール本文を表示")
    args = p.parse_args()

    report = fetch_latest_weekly_report()
    if not report:
        logger.warning("[skip] 最新の週次レポートが見つかりません")
        return

    alerts = fetch_latest_alerts()
    subject, body = build_mail_body(report, alerts)

    if args.dry_run:
        print(f"=== Subject ===\n{subject}\n")
        print(f"=== Body ===\n{body}")
        return

    send_mail(subject, body)


if __name__ == "__main__":
    main()
