"""
main.py
JPX投資主体別売買動向 自動分析システム
メインエントリーポイント（手動実行・n8nから呼び出し共通）

使い方:
  python main.py                        # 今週を自動取得・分析
  python main.py --mode manual          # 手動CSVモード（対話形式）
  python main.py --spot x.csv --futures y.csv --date 2025-01-10
  python main.py --monthly 2025-01      # 月次サマリー再集計
  python main.py --report-only          # 取得済みデータでレポートのみ再生成
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / "config" / ".env")

# ─────────────────────────────────────────
# ログ設定
# ─────────────────────────────────────────
LOG_DIR = Path(os.getenv("LOG_DIR", "./logs"))
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            LOG_DIR / f"jpx_{datetime.now().strftime('%Y%m%d')}.log",
            encoding="utf-8"
        ),
    ]
)
logger = logging.getLogger("main")

# ─────────────────────────────────────────
# モジュールのインポート
# ─────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from db           import supabase_client as db
from scripts      import fetch_jpx, analyze_jpx, build_excel as excel_builder
from agents       import report_agent

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./outputs"))


# ─────────────────────────────────────────
# 共通ヘルパー
# ─────────────────────────────────────────
def _get_week_date() -> date:
    """集計基準日（週末の金曜日）を返す。
    JPXは木曜日に前週（月〜金）のデータを公開するため、
    木曜実行時は翌日（金曜）を基準日とする。
    """
    today = date.today()
    weekday = today.weekday()  # 0=月 ... 4=金 ... 6=日
    # JPXは木曜に「前の週（〜金曜）」のデータを公表する。
    # 木曜を含む全曜日で「直近の金曜」を返す。
    days_since_friday = (weekday - 4) % 7
    return today if days_since_friday == 0 else today - timedelta(days=days_since_friday)


def _save_markdown(content: str, week_date: date) -> Path:
    dir_ = OUTPUT_DIR / "reports"
    dir_.mkdir(parents=True, exist_ok=True)
    # 期間（月曜〜金曜）でファイル名を構成: jpx_investor_YYYYMMDD_YYYYMMDD.md
    week_start = week_date - timedelta(days=4)
    fname = f"jpx_investor_{week_start.strftime('%Y%m%d')}_{week_date.strftime('%Y%m%d')}.md"
    path  = dir_ / fname
    path.write_text(content, encoding="utf-8")
    logger.info(f"[MD] 保存: {path}")
    return path


def _save_monthly_markdown(content: str, year_month: str) -> Path:
    dir_ = OUTPUT_DIR / "reports"
    dir_.mkdir(parents=True, exist_ok=True)
    fname = f"jpx_monthly_{year_month.replace('-', '')}.md"
    path  = dir_ / fname
    path.write_text(content, encoding="utf-8")
    logger.info(f"[月次MD] 保存: {path}")
    return path


def _save_excel(week_date: date) -> Path:
    year = week_date.year
    dir_ = OUTPUT_DIR / "excel"
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / f"jpx_investor_{year}.xlsx"

    # 全データを取得（Zスコア計算用）・年フィルター済みを行表示用に使う
    all_spot    = []
    all_futures = []
    for inv in analyze_jpx.INVESTORS:
        all_spot    += db.fetch_spot_history(inv, 260)
        all_futures += db.fetch_futures_history(inv, 260)

    spot_hist    = [r for r in all_spot    if r["week_date"][:4] == str(year)]
    futures_hist = [r for r in all_futures if r["week_date"][:4] == str(year)]

    monthly_data = [r for r in db.fetch_monthly_summary(60)
                    if r["year_month"][:4] == str(year)]
    return excel_builder.build_excel(
        spot_hist, futures_hist, monthly_data, path,
        all_spot_history=all_spot, all_futures_history=all_futures
    )


# ─────────────────────────────────────────
# メインフロー
# ─────────────────────────────────────────
def run_weekly(week_date: date, spot_path: str = None,
               futures_path: str = None, index_close: float = 0.0,
               market_data: dict | None = None):
    """週次分析の全フロー"""
    t0 = time.time()
    logger.info(f"=== 週次分析開始: {week_date} ===")

    # ① データ取得
    if spot_path or futures_path:
        logger.info("[取得] 手動CSVモード")
        fetch_result = fetch_jpx.parse_manual(
            spot_path=spot_path,
            futures_path=futures_path,
            week_date=week_date,
            index_close=index_close,
        )
    else:
        logger.info("[取得] 自動取得モード（JPXサイト）")
        fetch_result = fetch_jpx.fetch_all(week_date, index_close)

    spot_rows    = fetch_result.get("spot", [])
    futures_rows = fetch_result.get("futures", [])
    options_rows = fetch_result.get("options", [])
    errors       = fetch_result.get("errors", [])
    resolved_wd  = fetch_result.get("resolved_week_date")

    # JPX 記載の対象期間が呼び出し側の指定と異なる場合は実態を採用
    if resolved_wd and resolved_wd != week_date:
        logger.warning(
            f"[week_date補正] 指定 {week_date} → JPX実態 {resolved_wd} に変更"
        )
        week_date = resolved_wd

    if errors:
        for e in errors:
            logger.warning(f"[警告] {e}")

    if not spot_rows and not futures_rows:
        logger.error("[エラー] データが取得できませんでした")
        db.save_log(week_date, "error", error_message="データ取得失敗")
        return

    # ② Supabaseに蓄積
    n_spot    = db.upsert_spot(spot_rows)
    n_futures = db.upsert_futures(futures_rows)
    # week_date を resolved_wd で再付与（resolved_wd と元のラベルが乖離してたケース対応）
    if options_rows and resolved_wd:
        for r in options_rows:
            r["week_date"] = str(resolved_wd)
    n_options = db.upsert_options(options_rows) if options_rows else 0
    logger.info(f"[DB] 現物={n_spot}件, 先物={n_futures}件, オプション={n_options}件 upsert完了")

    # ③ 合算計算
    combined = analyze_jpx.build_combined(spot_rows, futures_rows, week_date)
    db.upsert_combined(combined)

    # ④ Zスコア・統計計算
    stats = analyze_jpx.build_stats(week_date, db)
    db.upsert_stats(stats)

    # ⑤ 分析コンテキスト構築
    context = analyze_jpx.build_analysis_context(week_date, db)

    # ⑥ AIレポート生成
    report_md = report_agent.generate_weekly_report(week_date, context, market_data=market_data)

    # ⑦ ファイル保存
    md_path = _save_markdown(report_md, week_date)
    db.save_report(week_date, "weekly", "markdown",
                   md_path.name, content_md=report_md)

    xlsx_path = _save_excel(week_date)
    db.save_report(week_date, "weekly", "excel", xlsx_path.name)

    # ⑧ ログ記録
    duration = time.time() - t0
    db.save_log(week_date, "success",
                spot_rows=n_spot, futures_rows=n_futures,
                duration_sec=duration)

    logger.info(f"=== 完了: {duration:.1f}秒 ===")
    logger.info(f"  Markdown: {md_path}")
    logger.info(f"  Excel:    {xlsx_path}")

    # ⑨ ターミナルにサマリーを表示
    print("\n" + "="*60)
    print(f"[OK] JPX需給分析完了: {week_date}")
    print("="*60)
    # エグゼクティブサマリー部分だけ抜き出して表示
    for line in report_md.split("\n"):
        if "エグゼクティブ" in line or (
            len(line) > 5 and not line.startswith("#") and not line.startswith("|")
            and report_md.find("エグゼクティブ") < report_md.find(line) < report_md.find("## 🌍")
        ):
            if line.strip():
                print(line.encode(sys.stdout.encoding, errors="replace").decode(sys.stdout.encoding))
    print("="*60)

    return {"md_path": md_path, "xlsx_path": xlsx_path, "report_md": report_md}


def run_monthly(year_month: str):
    """月次サマリー再集計 + レポート生成"""
    import calendar
    logger.info(f"=== 月次集計: {year_month} ===")

    # ① 月次サマリーをDB保存
    rows = analyze_jpx.build_monthly(year_month, db)
    n = db.upsert_monthly(rows)
    logger.info(f"[月次] {n}件保存完了")

    # ② 直近13ヶ月分を取得してAIレポート生成
    monthly_rows = db.fetch_monthly_summary(13)
    report_md = report_agent.generate_monthly_report(year_month, monthly_rows)

    # ③ ファイル保存
    md_path = _save_monthly_markdown(report_md, year_month)

    # ④ Supabaseのreportsテーブルに記録（week_date は月末日で代用）
    year, month = int(year_month[:4]), int(year_month[5:7])
    last_day = calendar.monthrange(year, month)[1]
    month_end = date(year, month, last_day)
    db.save_report(month_end, "monthly", "markdown", md_path.name, content_md=report_md)

    logger.info(f"[月次レポート] 完了: {md_path}")
    print(f"\n[OK] 月次需給レポート生成完了: {year_month}")
    print(f"     保存先: {md_path}")


def run_report_only(week_date: date, market_data: dict | None = None):
    """取得済みデータでレポートのみ再生成"""
    logger.info(f"=== レポート再生成: {week_date} ===")
    context   = analyze_jpx.build_analysis_context(week_date, db)
    report_md = report_agent.generate_weekly_report(week_date, context, market_data=market_data)
    md_path   = _save_markdown(report_md, week_date)
    db.save_report(week_date, "weekly", "markdown", md_path.name, content_md=report_md)
    logger.info(f"[再生成] 完了: {md_path}")


# ─────────────────────────────────────────
# CLI
# ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="JPX投資主体別売買動向 自動分析システム")
    parser.add_argument("--mode",        choices=["auto", "manual"], default="auto")
    parser.add_argument("--spot",        help="現物CSVのパス（手動モード）")
    parser.add_argument("--futures",     help="先物CSVのパス（手動モード）")
    parser.add_argument("--date",        help="集計基準日 YYYY-MM-DD（省略時は直近金曜）")
    parser.add_argument("--index-close", type=float, default=0.0, help="指数終値（先物換算用）")
    parser.add_argument("--monthly",     help="月次サマリー集計 YYYY-MM")
    parser.add_argument("--report-only", action="store_true", help="レポートのみ再生成")
    parser.add_argument("--vix",        type=float, help="VIX現在値（例: 18.5）")
    parser.add_argument("--nikkei-vi",  type=float, help="日経VI現在値（例: 22.0）")
    parser.add_argument("--usdjpy",     type=float, help="USD/JPYレート（例: 143.50）")
    parser.add_argument("--us10y",      type=float, help="米10年債利回り（例: 4.35）")
    parser.add_argument("--nk225",      type=float, help="日経225終値（例: 35800）")
    args = parser.parse_args()

    # 日付決定
    if args.date:
        week_date = date.fromisoformat(args.date)
    else:
        week_date = _get_week_date()

    # 市場数値をdictに集約（指定された引数のみ）
    market_data = {}
    if args.vix        is not None: market_data["vix"]       = args.vix
    if args.nikkei_vi  is not None: market_data["nikkei_vi"] = args.nikkei_vi
    if args.usdjpy     is not None: market_data["usdjpy"]    = args.usdjpy
    if args.us10y      is not None: market_data["us10y"]     = args.us10y
    if args.nk225      is not None: market_data["nk225"]     = args.nk225
    market_data = market_data or None  # 空なら None（ファイル読み込みにフォールバック）

    # モード分岐
    if args.monthly:
        run_monthly(args.monthly)
    elif args.report_only:
        run_report_only(week_date, market_data=market_data)
    else:
        run_weekly(
            week_date=week_date,
            spot_path=args.spot,
            futures_path=args.futures,
            index_close=args.index_close,
            market_data=market_data,
        )


if __name__ == "__main__":
    main()
