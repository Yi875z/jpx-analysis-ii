"""週次自動実行の「黙って終わらない」ガード（main.run_weekly の①-0〜①-c）。

JPX にも DB にも Claude API にも触らない。fetch_jpx.fetch_all と db を偽物に差し替え、
どの状況で exit 1（＝GitHub Actions の失敗＋失敗メール）になるかだけを見る。
背景: 2026-10-02 の実行は、現物の新形式ファイル名を読めず対象週を取り違えたうえ
「部分公表スキップ」として success で終わり、9/18週・9/25週のレポートが欠落した。
"""

from datetime import date

import pytest

import main
from scripts.parse_spot_xls import SPOT_INVESTORS

PUBLISHED = [date(2026, 9, 4), date(2026, 9, 11), date(2026, 9, 18), date(2026, 9, 25)]


def _spot(week):
    return [{"week_date": str(week), "investor_type": t} for t in SPOT_INVESTORS]


def _fetch_result(spot_week=date(2026, 9, 25), fut_week=date(2026, 9, 25), spot=True, errors=()):
    return {
        "spot": _spot(spot_week) if spot else [],
        "futures": [{"week_date": str(fut_week)}],
        "options": [],
        "errors": list(errors),
        "resolved_week_date": spot_week,
        "resolved_futures_week_date": fut_week,
        "published_spot_weeks": PUBLISHED,
    }


class _StopBeforeDbWrite(Exception):
    """ガードを通過して DB 書き込みに進んだことを示す（テストではここで止める）。"""


@pytest.fixture
def run(monkeypatch, tmp_path):
    """reported: レポート生成済みの週の集合。戻り値: (status, exit_code)。"""
    monkeypatch.setattr(main, "OUTPUT_DIR", tmp_path)
    logs = []

    def _run(fetch_result, reported):
        monkeypatch.setattr(main.fetch_jpx, "fetch_all", lambda wd, ic: fetch_result)
        monkeypatch.setattr(main.db, "weekly_report_exists", lambda w: w in reported)
        monkeypatch.setattr(main.db, "save_log", lambda *a, **k: logs.append((a, k)))

        def _stop(*a, **k):
            raise _StopBeforeDbWrite

        monkeypatch.setattr(main.fetch_index, "get_close_on_or_before", _stop)
        try:
            main.run_weekly(date(2026, 10, 2))
            code = 0
        except SystemExit as e:
            code = e.code
        except _StopBeforeDbWrite:
            code = "proceed"
        status = (tmp_path / "last_run_status.txt").read_text(encoding="utf-8").split()[0] \
            if (tmp_path / "last_run_status.txt").exists() else None
        return status, code

    return _run


def test_skipped_previous_week_fails(run):
    """9/18週と9/25週が両方掲載済みで 9/18週のレポートが無い → 最新週を作る前に失敗させる。"""
    status, code = run(_fetch_result(), reported={date(2026, 9, 4), date(2026, 9, 11)})
    assert (status, code) == ("missing_previous_week", 1)


def test_unreadable_spot_fails(run):
    status, code = run(_fetch_result(spot=False, errors=["現物取得エラー: x"]),
                       reported=set(PUBLISHED))
    assert (status, code) == ("spot_unreadable", 1)


def test_week_mismatch_fails_instead_of_silent_success(run):
    """旧挙動は partial_data で success 終了だった。"""
    reported = {date(2026, 9, 4), date(2026, 9, 11), date(2026, 9, 18)}
    status, code = run(_fetch_result(fut_week=date(2026, 9, 18)), reported=reported)
    assert (status, code) == ("week_mismatch", 1)


def test_already_generated_is_quiet_skip(run):
    """JPX未公表で処理済みの週を掴んだだけなら、従来どおり静かにスキップ（失敗にしない）。"""
    status, code = run(_fetch_result(), reported=set(PUBLISHED))
    assert (status, code) == ("no_new_data", 0)


def test_new_week_with_complete_history_proceeds(run):
    reported = {date(2026, 9, 4), date(2026, 9, 11), date(2026, 9, 18)}
    status, code = run(_fetch_result(), reported=reported)
    assert code == "proceed"
