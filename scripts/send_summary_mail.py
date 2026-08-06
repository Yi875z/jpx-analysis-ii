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


# 完結したレポートの最終行はこのいずれかで終わる（免責文・表・強調など）。
# max_tokens 切断は文中で唐突に終わるため、末尾文字だけで高精度に判定できる。
_COMPLETE_TAILS = tuple("。」）)*|！？!?％%円")


def _output_cap_chars() -> tuple[int, int]:
    """「上限接近」を警告する文字数と、その根拠の max_tokens を返す。

    以前は 15,000字 / 16,384トークンをハードコードしていたため、
    max_tokens を引き上げた後も古い上限で警告していた。実設定から導出する。
    日本語レポートの実測は約0.87トークン/字なので、上限の75%相当を閾値とする。
    """
    try:
        from agents.report_agent import MAX_TOKENS
    except Exception:
        return 0, 0
    return int(MAX_TOKENS * 0.75 / 0.87), MAX_TOKENS


def report_health(content: str) -> tuple[bool, str]:
    """レポート末尾の完結性を簡易判定し、(正常か, 説明文) を返す"""
    text = (content or "").rstrip()
    if not text:
        return False, "本文が空です"
    last_line = text.split("\n")[-1].strip()
    n = len(text)
    if not last_line.endswith(_COMPLETE_TAILS):
        return False, f"途中切断の疑い（{n:,}字・末尾「…{last_line[-12:]}」）"
    cap_chars, cap_tokens = _output_cap_chars()
    if cap_chars and n > cap_chars:
        return True, f"全文生成OK（{n:,}字）※出力上限{cap_tokens:,}トークンに接近中"
    return True, f"全文生成OK（{n:,}字）"


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


def _model_label() -> str:
    """メール本文に出す生成モデル名。

    以前は "Claude Sonnet 4.6" をハードコードしており、本番が Opus に切り替わった後も
    古い名前を送り続けていた。実際に使われる設定値から組み立てて食い違いを防ぐ。
    """
    raw = os.environ.get("CLAUDE_MODEL", "")
    if not raw:
        try:
            from agents.report_agent import DEFAULT_MODEL
            raw = DEFAULT_MODEL
        except Exception:
            return "Claude"
    pretty = {"claude-opus-5": "Claude Opus 5", "claude-opus-4-8": "Claude Opus 4.8",
              "claude-sonnet-5": "Claude Sonnet 5", "claude-sonnet-4-6": "Claude Sonnet 4.6"}
    return pretty.get(raw, raw)


def _lint_block() -> str:
    """公開前チェック（agents/report_lint.py）の結果をメール本文用に整形する。

    report_agent が outputs/last_lint.txt に書き出したものを読む。
    ファイルが無い場合（旧レポートの再送・レポートのみ再生成前）は何も表示しない。
    """
    path = Path(os.environ.get("OUTPUT_DIR", "./outputs")) / "last_lint.txt"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    if not text or text == "OK":
        return ""
    lines = text.splitlines()
    n_p0 = sum(1 for ln in lines if ln.startswith("[P0]"))
    head = f"🔍 公開前チェック: {len(lines)} 件検出（P0={n_p0} 件）"
    if n_p0:
        head += "\n   ※P0はレポートの結論が反転し得る違反です。本文を確認してください。"
    return head + "\n\n" + "\n".join(f"  {ln}" for ln in lines) + "\n\n"


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

    healthy, health_note = report_health(content)
    status_line = ("✅ " if healthy else "⚠️ ") + health_note

    lint_block = _lint_block()

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
【生成ステータス】 {status_line}

{alert_block}{lint_block}【エグゼクティブサマリー】

{summary}

────────────────────────────────────────
📊 ダッシュボード（全文閲覧・グラフ・オプション分析）:
{DASHBOARD_URL}

⚙ 取得処理: GitHub Actions による自動実行
🤖 AIレポート生成: {_model_label()}
"""
    subject = f"[JPX需給] {period_label} レポート完成 ({len(alerts)} アラート)" if alerts \
              else f"[JPX需給] {period_label} レポート完成"
    if not healthy:
        subject = f"[JPX需給] ⚠️ {period_label} レポート生成に問題あり"
    elif "[P0]" in lint_block:
        subject = f"[JPX需給] ⚠️ {period_label} 公開前チェックP0検出"
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
        host = (os.environ.get("SMTP_HOST") or "smtp.gmail.com").strip()
        port_str = (os.environ.get("SMTP_PORT") or "587").strip()
        port = int(port_str)
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
