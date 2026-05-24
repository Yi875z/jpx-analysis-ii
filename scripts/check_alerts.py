"""
scripts/check_alerts.py
=======================
最新週のDB状況を評価し、需給シグナル異常を検知してアラートを出す。

判定ルール:
  1. 海外現物 Zスコア（52w）| > 2.0  → 統計的異常
  2. 海外先物 Zスコア（52w）| > 2.0  → 統計的異常
  3. 海外 PCR > 1.8 または < 0.6     → ヘッジ姿勢の極端化
  4. ツインエンジン点灯/解除（前週比較） → トレンド転換
  5. MM ガンマ判定が +GEX ↔ -GEX に切替 → ボラ環境変化
  6. 海外 mini プット net > 20,000枚 → 大規模下方ヘッジ

出力:
  outputs/alerts/latest.json   ← 最新評価結果
  outputs/alerts/{date}.json   ← 日付別アーカイブ

SMTP 設定が .env にあれば Gmail でも送信。未設定ならスキップ（エラーにしない）。

呼び出し:
  python scripts/check_alerts.py                  # 最新週で評価
  python scripts/check_alerts.py --date 2026-05-15
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import smtplib
import sys
from collections import defaultdict
from datetime import date
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
from scripts import analyze_jpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "outputs" / "alerts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────
# 閾値（.env で上書き可能）
# ─────────────────────────────────────────
ZSCORE_THRESHOLD = float(os.environ.get("ALERT_ZSCORE_THRESHOLD", 2.0))
PCR_HIGH         = float(os.environ.get("ALERT_PCR_HIGH", 1.8))
PCR_LOW          = float(os.environ.get("ALERT_PCR_LOW", 0.6))
MINI_PUT_LARGE   = int(os.environ.get("ALERT_MINI_PUT_LARGE", 20000))


def _latest_week_in_db() -> date | None:
    """weekly_combined の最新 week_date を取得"""
    sb = db.get_client()
    res = (sb.table("weekly_combined").select("week_date")
             .order("week_date", desc=True).limit(1).execute())
    if not res.data:
        return None
    s = res.data[0]["week_date"]
    return date.fromisoformat(s)


def _prev_week_combined(week_date: date) -> dict:
    """前週の weekly_combined を {investor: row} で返す"""
    sb = db.get_client()
    res = (sb.table("weekly_combined").select("*")
             .lt("week_date", str(week_date))
             .order("week_date", desc=True)
             .limit(20).execute())
    rows = res.data or []
    if not rows:
        return {}
    prev_wd = rows[0]["week_date"]
    return {r["investor_type"]: r for r in rows if r["week_date"] == prev_wd}


def evaluate(week_date: date) -> dict:
    """指定週のアラート評価結果を返す"""
    ctx = analyze_jpx.build_analysis_context(week_date, db)
    options_rows = ctx.get("options_rows", [])

    alerts: list[dict] = []
    foreign = next((i for i in ctx["investors"] if i["key"] == "foreign"), None)

    # ── 1. 海外現物 Zスコア ───────────────────────────────
    if foreign and foreign.get("zscore_52w") is not None:
        z = foreign["zscore_52w"]
        if abs(z) > ZSCORE_THRESHOLD:
            alerts.append({
                "level": "high",
                "type": "spot_zscore_extreme",
                "title": f"海外 現物Zスコア(52w) 異常: {z:+.2f}",
                "message": f"海外投資家の現物フローが統計的異常水準。{'過熱（買い越し）' if z > 0 else 'セリングクライマックス候補（売り越し）'}。",
                "value": z, "threshold": ZSCORE_THRESHOLD,
            })

    # ── 2. 海外先物 Zスコア ───────────────────────────────
    if foreign and foreign.get("futures_zscore_52w") is not None:
        z = foreign["futures_zscore_52w"]
        if abs(z) > ZSCORE_THRESHOLD:
            alerts.append({
                "level": "high",
                "type": "futures_zscore_extreme",
                "title": f"海外 先物Zスコア(52w) 異常: {z:+.2f}",
                "message": f"海外投資家の先物フローが統計的異常水準。{'大型買い圧力' if z > 0 else '大型売り圧力'}。",
                "value": z, "threshold": ZSCORE_THRESHOLD,
            })

    # ── 3. 海外 PCR ───────────────────────────────────────
    fopt = defaultdict(int)
    for r in options_rows:
        if r["investor_type"] == "foreign":
            fopt[r["option_type"]] += r.get("net_lots", 0) or 0
    f_call = fopt.get("nikkei225_call", 0) + fopt.get("nikkei225_mini_call", 0)
    f_put  = fopt.get("nikkei225_put", 0)  + fopt.get("nikkei225_mini_put", 0)
    pcr = None
    if f_call > 0:
        pcr = f_put / f_call
        if pcr > PCR_HIGH:
            alerts.append({
                "level": "high",
                "type": "pcr_high",
                "title": f"海外 PCR が異常高水準: {pcr:.2f}",
                "message": f"プット買い偏重 = 下方ヘッジ姿勢が極端に強い。リスクオフ警戒。",
                "value": round(pcr, 2), "threshold": PCR_HIGH,
            })
        elif pcr < PCR_LOW:
            alerts.append({
                "level": "medium",
                "type": "pcr_low",
                "title": f"海外 PCR が異常低水準: {pcr:.2f}",
                "message": f"コール買い偏重 = 上方期待が極端に強い。短期過熱に注意。",
                "value": round(pcr, 2), "threshold": PCR_LOW,
            })

    # ── 4. ツインエンジン点灯/解除 ───────────────────────
    prev_map = _prev_week_combined(week_date)
    cur_twin = bool(foreign and foreign.get("is_twin_buy"))
    prev_twin = bool(prev_map.get("foreign", {}).get("is_twin_engine"))
    if cur_twin and not prev_twin:
        alerts.append({
            "level": "high",
            "type": "twin_engine_on",
            "title": "🟢 ツインエンジン 点灯",
            "message": "海外投資家が現物・先物の両方で買い越し転換。最強強気シグナル。",
            "value": True, "threshold": None,
        })
    elif (not cur_twin) and prev_twin:
        alerts.append({
            "level": "medium",
            "type": "twin_engine_off",
            "title": "🟡 ツインエンジン 解除",
            "message": "前週まで点灯していたツインエンジンが解除。上昇モメンタムの減衰。",
            "value": False, "threshold": None,
        })

    # ── 5. MM ガンマ判定（自己のオプション net） ─────────
    dopt = defaultdict(int)
    for r in options_rows:
        if r["investor_type"] == "dealer":
            dopt[r["option_type"]] += r.get("net_lots", 0) or 0
    d_call = dopt.get("nikkei225_call", 0) + dopt.get("nikkei225_mini_call", 0)
    d_put  = dopt.get("nikkei225_put", 0)  + dopt.get("nikkei225_mini_put", 0)
    gex = "neutral"
    if d_call < 0 and d_put < 0:
        gex = "-GEX"
    elif d_call > 0 and d_put > 0:
        gex = "+GEX"

    # 前週GEX計算
    if prev_map:
        prev_wd_str = next(iter(prev_map.values())).get("week_date") if prev_map else None
        if prev_wd_str:
            try:
                prev_options = db.fetch_week_options(date.fromisoformat(prev_wd_str))
            except Exception:
                prev_options = []
            popt = defaultdict(int)
            for r in prev_options:
                if r["investor_type"] == "dealer":
                    popt[r["option_type"]] += r.get("net_lots", 0) or 0
            p_call = popt.get("nikkei225_call", 0) + popt.get("nikkei225_mini_call", 0)
            p_put  = popt.get("nikkei225_put", 0)  + popt.get("nikkei225_mini_put", 0)
            prev_gex = "neutral"
            if p_call < 0 and p_put < 0: prev_gex = "-GEX"
            elif p_call > 0 and p_put > 0: prev_gex = "+GEX"
            if gex != prev_gex and prev_gex != "neutral":
                alerts.append({
                    "level": "high",
                    "type": "gex_regime_change",
                    "title": f"GEX 環境 切替: {prev_gex} → {gex}",
                    "message": f"マーケットメーカーのガンマ・ポジションが反転。ボラ環境変化シグナル。",
                    "value": gex, "threshold": prev_gex,
                })

    # ── 6. 海外 mini プット 大量買い越し ───────────────
    f_mini_put = fopt.get("nikkei225_mini_put", 0)
    if f_mini_put > MINI_PUT_LARGE:
        alerts.append({
            "level": "medium",
            "type": "foreign_mini_put_surge",
            "title": f"海外 ミニプット 大量買い越し: {f_mini_put:+,}枚",
            "message": "下方ヘッジ需要が急増。外部リスク警戒の表れ。",
            "value": f_mini_put, "threshold": MINI_PUT_LARGE,
        })

    return {
        "week_date": str(week_date),
        "evaluated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "alerts": alerts,
        "metrics": {
            "foreign_spot_zscore_52w":    foreign and foreign.get("zscore_52w"),
            "foreign_futures_zscore_52w": foreign and foreign.get("futures_zscore_52w"),
            "foreign_pcr": round(pcr, 2) if pcr is not None else None,
            "twin_engine": cur_twin,
            "gex": gex,
            "foreign_mini_put_net": f_mini_put,
        },
        "thresholds": {
            "zscore": ZSCORE_THRESHOLD,
            "pcr_high": PCR_HIGH,
            "pcr_low":  PCR_LOW,
            "mini_put_large": MINI_PUT_LARGE,
        },
    }


def write_outputs(result: dict) -> Path:
    latest = OUTPUT_DIR / "latest.json"
    dated  = OUTPUT_DIR / f"{result['week_date']}.json"
    for p in (latest, dated):
        p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"[alerts] {latest} に書き出し（{len(result['alerts'])} 件）")
    return latest


def send_mail_if_configured(result: dict) -> bool:
    """SMTP 設定があれば Gmail で送信。なければスキップ。"""
    user = os.environ.get("SMTP_USER") or os.environ.get("NOTIFY_EMAIL")
    pw   = os.environ.get("SMTP_APP_PASSWORD") or os.environ.get("SMTP_PASSWORD")
    to   = os.environ.get("NOTIFY_EMAIL") or user
    if not (user and pw and to):
        logger.info("[alerts] SMTP 未設定のためメール送信スキップ "
                    "(.env に SMTP_USER / SMTP_APP_PASSWORD を設定すると送信される)")
        return False
    if not result["alerts"]:
        logger.info("[alerts] 該当アラートなしのためメール送信スキップ")
        return False

    lines = [f"JPX需給アラート（{result['week_date']}週）",
             f"検出件数: {len(result['alerts'])}", "", "─" * 50]
    for a in result["alerts"]:
        lines += [f"[{a['level'].upper()}] {a['title']}", f"  → {a['message']}", ""]
    lines += ["─" * 50, "（このメールは check_alerts.py から自動送信されています）"]
    body = "\n".join(lines)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"[JPX需給アラート] {len(result['alerts'])}件検出 ({result['week_date']})"
    msg["From"] = user
    msg["To"] = to

    try:
        host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        port = int(os.environ.get("SMTP_PORT", 587))
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
        logger.info(f"[alerts] メール送信成功: {to}")
        return True
    except Exception as e:
        logger.warning(f"[alerts] メール送信失敗: {e}")
        return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="評価対象週末日 (YYYY-MM-DD)。省略時は最新週")
    p.add_argument("--no-mail", action="store_true", help="メール送信スキップ")
    args = p.parse_args()

    if args.date:
        wd = date.fromisoformat(args.date)
    else:
        wd = _latest_week_in_db()
        if wd is None:
            logger.error("DBに weekly_combined データがありません")
            sys.exit(1)

    print(f"=== アラート評価: {wd} ===\n")
    result = evaluate(wd)

    if not result["alerts"]:
        print("✅ 該当アラートなし\n")
    else:
        print(f"⚠️ {len(result['alerts'])} 件のアラートを検出:\n")
        for a in result["alerts"]:
            print(f"  [{a['level'].upper()}] {a['title']}")
            print(f"     → {a['message']}\n")

    print("--- メトリクス ---")
    for k, v in result["metrics"].items():
        print(f"  {k}: {v}")
    print()

    write_outputs(result)
    if not args.no_mail:
        send_mail_if_configured(result)


if __name__ == "__main__":
    main()
